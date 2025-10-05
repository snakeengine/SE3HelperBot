# utils/feature_flags.py
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# استخدم نفس الأساس الموحّد في المشروع
try:
    from utils.paths import BASE
except Exception:
    BASE = Path(os.getenv("DATA_DIR", "/data")).resolve()

# ملفات التخزين تحت BASE (على الـ Volume)
FILE       = (BASE / "feature_flags.json")
MAINT_FILE = (BASE / "maintenance.json")

# مجلد نسخ احتياطية دوّارة
BACKUPS_DIR = (BASE / "backups")
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
MAX_BACKUPS = int(os.getenv("JSON_BACKUPS_KEEP", "7") or "7")

# ---------- قفل عبر العمليات ----------
_FILELOCK_PATH = (BASE / ".feature_flags.lock")

def _file_lock_acquire():
    _FILELOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        import msvcrt  # type: ignore
        fh = open(_FILELOCK_PATH, "a+b")
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        return ("win", fh)
    except Exception:
        try:
            import fcntl  # type: ignore
            fh = open(_FILELOCK_PATH, "a+b")
            fcntl.flock(fh, fcntl.LOCK_EX)
            return ("unix", fh)
        except Exception:
            return (None, None)

def _file_lock_release(tok):
    kind, fh = tok
    if not fh:
        return
    try:
        if kind == "win":
            import msvcrt  # type: ignore
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        elif kind == "unix":
            import fcntl  # type: ignore
            fcntl.flock(fh, fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        fh.close()
    except Exception:
        pass

def _snapshot(path: Path) -> None:
    try:
        if not path.exists():
            return
        ts = time.strftime("%Y%m%d-%H%M%S")
        dst = BACKUPS_DIR / f"{path.stem}.{ts}{path.suffix}"
        shutil.copy2(path, dst)
        fam = sorted(BACKUPS_DIR.glob(f"{path.stem}.*{path.suffix}"))
        if len(fam) > MAX_BACKUPS:
            for p in fam[:-MAX_BACKUPS]:
                try: p.unlink()
                except Exception: pass
    except Exception:
        pass

def _atomic_write_json(path: Path, d: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _snapshot(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

# ---------- ترحيل مسارات قديمة (مرة واحدة) ----------
def _maybe_migrate_legacy() -> None:
    # لو كان في نسخة قديمة داخل مجلد المشروع المحلي
    legacy_root = Path(__file__).resolve().parents[1] / "data"
    candidates = [
        legacy_root / "feature_flags.json",
        legacy_root / "maintenance.json",
    ]
    for src in candidates:
        if src.exists():
            dst = BASE / src.name
            if not dst.exists():
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                except Exception:
                    pass

_maybe_migrate_legacy()

# ======================= Defaults =======================
DEFAULT_TABS: List[Dict[str, str]] = [
    {"key": "vip",            "label_ar": "شراء/تفعيل VIP",     "label_en": "Buy/Activate VIP"},
    {"key": "download",       "label_ar": "تحميل التطبيق",       "label_en": "Download App"},
    {"key": "rewards",        "label_ar": "الجوائز",             "label_en": "Rewards"},
    {"key": "check",          "label_ar": "تحقق من جهازك",       "label_en": "Check Device"},
    {"key": "tools",          "label_ar": "أدوات الألعاب",       "label_en": "Game Tools"},
    {"key": "support",        "label_ar": "الدعم / البلاغ",      "label_en": "Support / Report"},
    {"key": "promoters",      "label_ar": "المروّجون",           "label_en": "Promoters"},
    {"key": "live",           "label_ar": "الدردشة الحيّة",       "label_en": "Live Chat"},
    {"key": "suppliers",      "label_ar": "المورّدون الموثوقون", "label_en": "Trusted Suppliers"},
    {"key": "safe_usage",     "label_ar": "الاستخدام الآمن",      "label_en": "Safe Usage"},
    {"key": "language",       "label_ar": "اللغة",               "label_en": "Language"},
    {"key": "alerts",         "label_ar": "صندوق الإشعارات",     "label_en": "Alerts Inbox"},
    {"key": "server_status",  "label_ar": "حالة السيرفرات",      "label_en": "Server Status"},
]

# ======================= IO helpers (tabs) =======================
def _ensure_defaults() -> dict:
    d = {"tabs": {}}
    for item in DEFAULT_TABS:
        d["tabs"][item["key"]] = {"enabled": True, "msg_ar": "", "msg_en": ""}
    _atomic_write_json(FILE, d)
    return d

def _load() -> dict:
    if not FILE.exists():
        return _ensure_defaults()
    tok = _file_lock_acquire()
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return _ensure_defaults()
    finally:
        _file_lock_release(tok)

def _save(d: dict) -> None:
    tok = _file_lock_acquire()
    try:
        _atomic_write_json(FILE, d)
    finally:
        _file_lock_release(tok)

def _labels_map() -> Dict[str, Dict[str, str]]:
    return {x["key"]: {"ar": x["label_ar"], "en": x["label_en"]} for x in DEFAULT_TABS}

def _ensure_tab(d: dict, name: str) -> dict:
    tabs = d.setdefault("tabs", {})
    row = tabs.get(name)
    if row is None:
        row = {"enabled": True, "msg_ar": "", "msg_en": ""}
        tabs[name] = row
    return row

# ======================= Public API (tabs) =======================
def list_tabs() -> List[Dict[str, object]]:
    d = _load()
    out: List[Dict[str, object]] = []
    labels = _labels_map()
    for item in DEFAULT_TABS:
        key = item["key"]
        row = d.get("tabs", {}).get(key, {})
        out.append({
            "key": key,
            "label_ar": item.get("label_ar", key),
            "label_en": item.get("label_en", key),
            "enabled": bool(row.get("enabled", True)),
            "msg_ar": str(row.get("msg_ar", "") or ""),
            "msg_en": str(row.get("msg_en", "") or ""),
        })
    # مفاتيح إضافية إن وُجدت
    for key, row in (d.get("tabs", {}) or {}).items():
        if key in labels:
            continue
        out.append({
            "key": key,
            "label_ar": key,
            "label_en": key,
            "enabled": bool(row.get("enabled", True)),
            "msg_ar": str(row.get("msg_ar", "") or ""),
            "msg_en": str(row.get("msg_en", "") or ""),
        })
    return out

def labels() -> Dict[str, Dict[str, str]]:
    return _labels_map()

def keys() -> List[str]:
    return [it["key"] for it in DEFAULT_TABS]

def get_flags() -> Dict[str, bool]:
    d = _load()
    for k in keys():
        _ensure_tab(d, k)
    _save(d)
    return {k: bool(v.get("enabled", True)) for k, v in d["tabs"].items()}

def is_enabled(name: str, *, user_id: int | None = None, default: bool = True) -> bool:
    d = _load()
    v = d.get("tabs", {}).get(name, {}).get("enabled", default)
    if isinstance(v, str):
        v = v.strip().lower() not in {"0", "false", "off"}
    return bool(v)

def set_enabled(name: str, enabled: bool) -> None:
    d = _load()
    row = _ensure_tab(d, name)
    row["enabled"] = bool(enabled)
    _save(d)

def enable(name: str) -> None:
    set_enabled(name, True)

def disable(name: str) -> None:
    set_enabled(name, False)

def toggle_tab(name: str) -> bool:
    d = _load()
    row = _ensure_tab(d, name)
    row["enabled"] = not bool(row.get("enabled", True))
    _save(d)
    return bool(row["enabled"])

def get_message(name: str, lang: str = "ar") -> str:
    d = _load()
    row = d.get("tabs", {}).get(name, {})
    if lang.lower().startswith("ar"):
        return str(row.get("msg_ar", "") or "")
    return str(row.get("msg_en", "") or "")

def set_message(name: str, text: str, lang: str = "ar") -> None:
    d = _load()
    row = _ensure_tab(d, name)
    if lang.lower().startswith("ar"):
        row["msg_ar"] = str(text or "")
    else:
        row["msg_en"] = str(text or "")
    _save(d)

def clear_message(name: str, lang: str | None = None) -> None:
    d = _load()
    row = d.get("tabs", {}).get(name)
    if not row:
        return
    if lang is None:
        row["msg_ar"] = ""
        row["msg_en"] = ""
    elif lang.lower().startswith("ar"):
        row["msg_ar"] = ""
    else:
        row["msg_en"] = ""
    _save(d)

def get_tab(name: str) -> Dict[str, object]:
    d = _load()
    row = d.get("tabs", {}).get(name)
    if row is None:
        row = _ensure_tab(d, name)
        _save(d)
    lab = _labels_map().get(name, {"ar": name, "en": name})
    return {
        "key": name,
        "enabled": bool(row.get("enabled", True)),
        "msg_ar": str(row.get("msg_ar", "") or ""),
        "msg_en": str(row.get("msg_en", "") or ""),
        "label_ar": lab["ar"],
        "label_en": lab["en"],
    }

def set_tab(
    name: str,
    *,
    enabled: bool | None = None,
    msg_ar: str | None = None,
    msg_en: str | None = None
) -> None:
    d = _load()
    row = _ensure_tab(d, name)
    if enabled is not None:
        row["enabled"] = bool(enabled)
    if msg_ar is not None:
        row["msg_ar"] = str(msg_ar or "")
    if msg_en is not None:
        row["msg_en"] = str(msg_en or "")
    _save(d)

# ======================= Maintenance (separate file) =======================
def _maint_load() -> dict:
    if not MAINT_FILE.exists():
        d = {"enabled": False, "msg_ar": "", "msg_en": ""}
        _atomic_write_json(MAINT_FILE, d)
        return d
    tok = _file_lock_acquire()
    try:
        return json.loads(MAINT_FILE.read_text(encoding="utf-8"))
    except Exception:
        d = {"enabled": False, "msg_ar": "", "msg_en": ""}
        _atomic_write_json(MAINT_FILE, d)
        return d
    finally:
        _file_lock_release(tok)

def _maint_save(d: dict) -> None:
    tok = _file_lock_acquire()
    try:
        _atomic_write_json(MAINT_FILE, d)
    finally:
        _file_lock_release(tok)

def maint_is_on() -> bool:
    return bool(_maint_load().get("enabled", False))

def maint_set(value: bool) -> None:
    d = _maint_load()
    d["enabled"] = bool(value)
    _maint_save(d)

def maint_toggle() -> bool:
    d = _maint_load()
    d["enabled"] = not bool(d.get("enabled", False))
    _maint_save(d)
    return bool(d["enabled"])

def maint_message(lang: str = "ar") -> str:
    d = _maint_load()
    if lang.lower().startswith("ar"):
        return str(d.get("msg_ar", "") or "")
    return str(d.get("msg_en", "") or "")

def maint_set_message(text: str, lang: str = "ar") -> None:
    d = _maint_load()
    if lang.lower().startswith("ar"):
        d["msg_ar"] = str(text or "")
    else:
        d["msg_en"] = str(text or "")
    _maint_save(d)

def maint_clear_message(lang: str | None = None) -> None:
    d = _maint_load()
    if lang is None:
        d["msg_ar"] = ""
        d["msg_en"] = ""
    elif lang.lower().startswith("ar"):
        d["msg_ar"] = ""
    else:
        d["msg_en"] = ""
    _maint_save(d)

def maint_get() -> Dict[str, object]:
    d = _maint_load()
    return {
        "enabled": bool(d.get("enabled", False)),
        "msg_ar": str(d.get("msg_ar", "") or ""),
        "msg_en": str(d.get("msg_en", "") or ""),
    }

# ======================= maintenance() callable (compat) =======================
def maintenance(lang: str = "ar"):
    """Return tuple: (enabled: bool, message: str)."""
    return maint_is_on(), maint_message(lang)

# خصائص/دوال لضمان التوافق مع dot-access
maintenance.is_on = staticmethod(maint_is_on)                  # type: ignore[attr-defined]
maintenance.set = staticmethod(maint_set)                      # type: ignore[attr-defined]
maintenance.toggle = staticmethod(maint_toggle)                # type: ignore[attr-defined]
maintenance.message = staticmethod(maint_message)              # type: ignore[attr-defined]
maintenance.set_message = staticmethod(maint_set_message)      # type: ignore[attr-defined]
maintenance.clear_message = staticmethod(maint_clear_message)  # type: ignore[attr-defined]
maintenance.get = staticmethod(maint_get)                      # type: ignore[attr-defined]

# -------- Aliases expected by other modules (compat) --------
def set_maintenance(value: bool) -> None:         maint_set(value)
def toggle_maintenance() -> bool:                 return maint_toggle()
def get_maintenance() -> Dict[str, object]:       return maint_get()
def maintenance_message(lang: str = "ar") -> str: return maint_message(lang)
def set_maintenance_message(text: str, lang: str = "ar") -> None:  maint_set_message(text, lang)
def clear_maintenance_message(lang: str | None = None) -> None:     maint_clear_message(lang)

# ======================= Extra aliases =======================
def set_tab_enabled(name: str, value: bool) -> None: set_tab(name, enabled=value)
def update_tab(name: str, **kwargs) -> None: set_tab(name, **kwargs)
def get_tab_msg(name: str, lang: str = "ar") -> str: return get_message(name, lang)
def set_tab_msg(name: str, text: str, lang: str = "ar") -> None: set_message(name, text, lang)
def clear_tab_msg(name: str, lang: str | None = None) -> None: clear_message(name, lang)
def all_data() -> dict: return _load()

__all__ = [
    # tabs
    "list_tabs", "labels", "keys", "get_flags",
    "is_enabled", "set_enabled", "enable", "disable", "toggle_tab",
    "get_message", "set_message", "clear_message",
    "get_tab", "set_tab",
    "set_tab_enabled", "update_tab", "get_tab_msg", "set_tab_msg", "clear_tab_msg",
    "all_data",
    # maintenance callable + helpers
    "maintenance",
    "maint_is_on", "maint_set", "maint_toggle",
    "maint_message", "maint_set_message", "maint_clear_message", "maint_get",
    # compat aliases
    "set_maintenance", "toggle_maintenance", "get_maintenance",
    "maintenance_message", "set_maintenance_message", "clear_maintenance_message",
]
