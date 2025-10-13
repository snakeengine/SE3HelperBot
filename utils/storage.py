# utils/storage.py
from __future__ import annotations

import os
import time
import mimetypes
import threading
from pathlib import Path
from typing import Optional

# =========================
# BASE PATH (دائم على Railway)
# =========================
# نحاول استخدام utils.paths لو موجود، ونوفّر بديلًا تلقائيًا
try:
    from utils.paths import safe_join as _safe_join, BASE as _BASE
except Exception:
    _BASE = Path(os.getenv("DATA_DIR", "/data")).resolve()
    def _safe_join(*parts: str) -> Path:
        # join آمن داخل BASE فقط
        p = _BASE.joinpath(*[str(x).lstrip("/\\") for x in parts]).resolve()
        if not str(p).startswith(str(_BASE)):
            raise ValueError("unsafe path escape")
        return p

BASE = _BASE
UPLOADS_BASE = _safe_join("uploads")  # كل ملفات التخزين المحلي تُحفظ هنا
UPLOADS_BASE.mkdir(parents=True, exist_ok=True)

# ================
# Cloudflare R2 (اختياري)
# ================
try:
    import boto3  # type: ignore
    from botocore.exceptions import ClientError  # type: ignore
except Exception:  # boto3 غير متاح
    boto3 = None
    class ClientError(Exception):  # fallback
        ...

R2_ENDPOINT = (os.getenv("R2_ENDPOINT") or "").strip()
R2_BUCKET   = (os.getenv("R2_BUCKET") or "").strip()
R2_KEY      = (os.getenv("R2_ACCESS_KEY_ID") or "").strip()
R2_SECRET   = (os.getenv("R2_SECRET_ACCESS_KEY") or "").strip()
R2_PUBLIC   = (os.getenv("R2_PUBLIC_BASE") or "").strip().rstrip("/")

def _r2_enabled() -> bool:
    return bool(boto3 and R2_ENDPOINT and R2_BUCKET and R2_KEY and R2_SECRET)

def _r2_client():
    assert _r2_enabled(), "R2 is not configured"
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_KEY,
        aws_secret_access_key=R2_SECRET,
    )

# =================
# أدوات كتابة ذرّية
# =================
_lock = threading.Lock()

def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{int(time.time()*1000)}.{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    # استبدال ذرّي (يعمل على ويندوز/لينكس)
    os.replace(tmp, path)

# =====================
# واجهة التخزين العامة
# =====================
def _norm_key(key: str) -> str:
    return str(key or "").lstrip("/")

def _guess_content_type(filename_or_key: str, fallback: str = "application/octet-stream") -> str:
    ct, _ = mimetypes.guess_type(filename_or_key)
    return ct or fallback

def put_bytes(key: str, data: bytes, content_type: Optional[str] = None) -> str:
    """
    يحفظ بايتات تحت `key`.
    - إن كانت إعدادات R2 متوفّرة ⇒ يرفع إلى R2 ويعيد رابطًا (عامًا لو R2_PUBLIC محدّد).
    - غير ذلك ⇒ يحفظ محليًا تحت /data/uploads ويعيد مسار file:// (دائم بوجود Volume).
    """
    key = _norm_key(key)
    content_type = content_type or _guess_content_type(key)

    if _r2_enabled():
        s3 = _r2_client()
        s3.put_object(Bucket=R2_BUCKET, Key=key, Body=data, ContentType=content_type)
        if R2_PUBLIC:
            return f"{R2_PUBLIC}/{key}"
        # رابط موقّت ساعة
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": R2_BUCKET, "Key": key},
            ExpiresIn=3600,
        )

    # تخزين محلي دائم (/data/uploads)
    dest = _safe_join("uploads", key)
    with _lock:
        _atomic_write_bytes(dest, data)
    return f"file://{dest}"

def get_bytes(key: str) -> Optional[bytes]:
    """
    يعيد محتوى الملف إذا كان موجودًا (R2 أو محلي).
    يرجّع None لو غير موجود.
    """
    key = _norm_key(key)

    if _r2_enabled():
        try:
            s3 = _r2_client()
            obj = s3.get_object(Bucket=R2_BUCKET, Key=key)
            return obj["Body"].read()
        except Exception:
            return None

    p = _safe_join("uploads", key)
    try:
        return p.read_bytes()
    except Exception:
        return None

def delete(key: str) -> bool:
    """يحذف الملف من R2 أو محليًا. يرجّع True لو تم الحذف."""
    key = _norm_key(key)

    if _r2_enabled():
        try:
            _r2_client().delete_object(Bucket=R2_BUCKET, Key=key)
            return True
        except Exception:
            return False

    p = _safe_join("uploads", key)
    try:
        if p.exists():
            p.unlink()
        return True
    except Exception:
        return False

def exists(key: str) -> bool:
    key = _norm_key(key)
    if _r2_enabled():
        try:
            _r2_client().head_object(Bucket=R2_BUCKET, Key=key)
            return True
        except Exception:
            return False
    return _safe_join("uploads", key).exists()

def url_for(key: str, *, expires: int = 3600) -> Optional[str]:
    """
    يعيد URL للوصول إلى العنصر:
    - R2: رابط عام إن R2_PUBLIC موجود، وإلا presigned.
    - محلي: يرجّع file://… (للإستخدام الداخلي). إن عندك خادم ستاتيك، عرّف LOCAL_PUBLIC_BASE.
    """
    key = _norm_key(key)

    if _r2_enabled():
        if R2_PUBLIC:
            return f"{R2_PUBLIC}/{key}"
        try:
            return _r2_client().generate_presigned_url(
                "get_object",
                Params={"Bucket": R2_BUCKET, "Key": key},
                ExpiresIn=int(expires),
            )
        except Exception:
            return None

    local_public = (os.getenv("LOCAL_PUBLIC_BASE") or "").rstrip("/")
    if local_public:
        return f"{local_public}/{key}"
    p = _safe_join("uploads", key)
    return f"file://{p}" if p.exists() else None

def local_debug_path() -> Path:
    """يعيد مجلد البيانات الأساسي (لتسهيل الفحص اليدوي)."""
    return BASE
