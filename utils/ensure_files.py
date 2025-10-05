# utils/ensure_files.py
from __future__ import annotations
import os
from pathlib import Path
from typing import Tuple

# استيراد المسارات من utils.paths (كلها Path objects)
from utils.paths import (
    BASE,
    shop_base,
    cache_base,
    inventory_base,
    FLAGS_PATH,
    SHOP_CFG,
    INV_BL_PATH,
)

def _ensure_dir(p: Path, mode: int = 0o755) -> None:
    """
    ينشئ المجلد إن لم يوجد ويضبط صلاحياته (لا يرفع لو فشل الضبط).
    كما يضيف .gitkeep ليسهّل تتبّع المجلد داخل المستودع.
    """
    p.mkdir(parents=True, exist_ok=True)
    try:
        p.chmod(mode)
    except Exception:
        pass
    try:
        (p / ".gitkeep").touch(exist_ok=True)
    except Exception:
        pass

def _atomic_write_json(path: Path, payload: str) -> None:
    """
    كتابة ذرّية: نكتب في ملف مؤقت بنفس المجلد ثم نستبدله.
    هذا يقلّل احتمال تلف الملف على المنصّات اللي توقف/تشغّل السيرفر.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(payload)
        try:
            f.flush()
            os.fsync(f.fileno())
        except Exception:
            # بيئات containers أحيانًا لا تدعم fsync—نتجاهل الخطأ بأمان
            pass
    os.replace(tmp, path)

def _ensure_json_file(path: Path) -> None:
    """ينشئ ملف JSON فارغ {} إن لم يكن موجودًا، مع صلاحيات مقروءة/قابلة للكتابة."""
    if not path.exists():
        _atomic_write_json(path, "{}")
        try:
            path.chmod(0o664)
        except Exception:
            pass

def ensure_required_files() -> Tuple[Path, Path, Path]:
    """
    ينشئ المجلدات/الملفات المطلوبة للتشغيل الأول.
    يُرجع (shop_base, cache_base, inventory_base) كمسارات.
    آمن للتنفيذ عدة مرات.
    """
    # تأكد من الجذر BASE أولًا (مثلاً /data على Railway)
    _ensure_dir(BASE)

    # أنشئ المجلدات الأساسية
    for d in (shop_base, cache_base, inventory_base):
        _ensure_dir(d)

    # أنشئ ملفات الإعدادات الفارغة إن لم توجد (ذرّية)
    _ensure_json_file(FLAGS_PATH)
    _ensure_json_file(SHOP_CFG)
    _ensure_json_file(INV_BL_PATH)

    return shop_base, cache_base, inventory_base
