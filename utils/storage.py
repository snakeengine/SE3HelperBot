# utils/storage.py
from __future__ import annotations
import os, time
from pathlib import Path
from typing import Optional
from utils.paths import safe_join, BASE

# محاولة استيراد boto3 اختياريًا
try:
    import boto3
    from botocore.exceptions import ClientError
except Exception:  # لو مش متوفّر
    boto3 = None
    class ClientError(Exception): ...
    
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

def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """
    يرفع الى R2 إن كان مفعّل؛ غير ذلك يخزن على الديسك تحت BASE.
    يعيد URL (عام إن توفر R2_PUBLIC، وإلا رابط موقّت).
    """
    key = key.lstrip("/")
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
    # تخزين محلي (غير دائم على Railway بدون Volume)
    p = safe_join("uploads", key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    # ارجع path محليًا كحلّ بديل
    return f"file://{p}"

def exists(key: str) -> bool:
    key = key.lstrip("/")
    if _r2_enabled():
        try:
            _r2_client().head_object(Bucket=R2_BUCKET, Key=key)
            return True
        except Exception:
            return False
    p = safe_join("uploads", key)
    return p.exists()

def local_debug_path() -> Path:
    return BASE
