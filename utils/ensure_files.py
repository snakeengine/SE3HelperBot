# utils/ensure_files.py
from __future__ import annotations
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

def ensure_required_files() -> Tuple[Path, Path, Path]:
    """
    ينشئ المجلدات/الملفات المطلوبة للتشغيل الأول.
    يُرجع (shop_base, cache_base, inventory_base) كمسارات.
    """
    # أنشئ المجلدات (بدون أقواس بعد أسماء المتغيرات لأنها Paths)
    for d in (shop_base, cache_base, inventory_base):
        d.mkdir(parents=True, exist_ok=True)

    # أنشئ ملفات الإعدادات الفارغة إذا غير موجودة
    if not FLAGS_PATH.exists():
        FLAGS_PATH.write_text("{}", encoding="utf-8")
    if not SHOP_CFG.exists():
        SHOP_CFG.write_text("{}", encoding="utf-8")
    if not INV_BL_PATH.exists():
        INV_BL_PATH.write_text("{}", encoding="utf-8")

    return shop_base, cache_base, inventory_base
