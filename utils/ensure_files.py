# utils/ensure_files.py
from __future__ import annotations
import json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # مجلد المشروع
LOCALES = ROOT / "locales"
DATA = ROOT / "data"

EN = LOCALES / "en.json"
AR = LOCALES / "ar.json"
USERS = DATA / "users.json"
USER_LANGS = ROOT / "user_langs.json"  # كما تستخدمه عندك

EN_KEYS = {
    "unknown_gate.unknown_message": "⛔ Unknown message. Only specific commands are allowed.",
    "unknown_gate.unknown_user": "⛔ This bot is restricted. Please send /start first."
}
AR_KEYS = {
    "unknown_gate.unknown_message": "⛔ رسالة غير معروفة. يُسمح فقط بأوامر محددة.",
    "unknown_gate.unknown_user": "⛔ هذا البوت مقيَّد. أرسل /start أولاً."
}

def _load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _save_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _ensure_locales():
    # EN
    en = _load_json(EN)
    changed = False
    for k, v in EN_KEYS.items():
        if en.get(k) != v:
            en[k] = v
            changed = True
    if changed or not EN.exists():
        _save_json(EN, en)

    # AR
    ar = _load_json(AR)
    changed = False
    for k, v in AR_KEYS.items():
        if ar.get(k) != v:
            ar[k] = v
            changed = True
    if changed or not AR.exists():
        _save_json(AR, ar)

def _ensure_data_files():
    DATA.mkdir(parents=True, exist_ok=True)
    if not USERS.exists():
        _save_json(USERS, {})  # أو [] إذا تفضّل قائمة
    if not USER_LANGS.exists():
        _save_json(USER_LANGS, {})

def ensure_required_files():
    _ensure_locales()
    _ensure_data_files()
