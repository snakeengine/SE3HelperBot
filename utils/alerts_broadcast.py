# utils/alerts_broadcast.py
from __future__ import annotations
import asyncio, json, time, datetime
from pathlib import Path
from typing import Dict, Any, Set, Optional, List, Tuple
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from utils.alerts_config import get_config

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
STATS_FILE   = DATA_DIR / "alerts_stats.json"
SUBS_FILE    = DATA_DIR / "alerts_subs.json"
ACTIVE_FILE  = DATA_DIR / "alerts_active.json"   # [ {id, ts, kind, text_en, text_ar, expires?} ]
USER_LANGS   = DATA_DIR / "user_langs.json"

# ---------- JSON helpers ----------
def _load_json(path: Path):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return None

def _save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------- recipients ----------
def _load_known_users() -> Set[int]:
    ids: Set[int] = set()
    for name in ("users.json", "known_users.json", "user_index.json"):
        p = DATA_DIR / name
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text("utf-8"))
            if isinstance(data, dict):
                for k in list(data.keys()):
                    if str(k).isdigit():
                        ids.add(int(k))
                if "users" in data and isinstance(data["users"], list):
                    for u in data["users"]:
                        uid = u.get("id") if isinstance(u, dict) else u
                        if str(uid).isdigit():
                            ids.add(int(uid))
            elif isinstance(data, list):
                for u in data:
                    uid = u.get("id") if isinstance(u, dict) else u
                    if str(uid).isdigit():
                        ids.add(int(uid))
        except Exception:
            continue
    return ids

def _load_subscriptions() -> Dict[str, bool]:
    return _load_json(SUBS_FILE) or {}

# ---------- stats ----------
def _inc_stats(kind: str, n: int):
    stats = _load_json(STATS_FILE) or {}
    now = datetime.date.today()
    wk = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    stats.setdefault(wk, {})
    stats[wk][kind] = int(stats[wk].get(kind, 0)) + int(n)
    _save_json(STATS_FILE, stats)

# ---------- active alerts store ----------
def _load_active() -> List[Dict[str, Any]]:
    return _load_json(ACTIVE_FILE) or []

def _save_active(lst: List[Dict[str, Any]]):
    _save_json(ACTIVE_FILE, lst)

def _gc_active(lst: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now = int(time.time())
    return [a for a in lst if not a.get("expires") or int(a["expires"]) > now]

def _pick_lang(uid: int) -> str:
    try:
        m = _load_json(USER_LANGS) or {}
        return str(m.get(str(uid), "ar"))
    except Exception:
        return "ar"

# <-- الدالة التي يحتاجها كودك -->
def get_active_alerts(lang: str) -> List[Dict[str, Any]]:
    """
    تُعيد قائمة الإشعارات النشطة مفلترة حسب الوقت،
    مع نص مُختار للغة المطلوبة.
    """
    now = int(time.time())
    raw = _gc_active(_load_active())
    out: List[Dict[str, Any]] = []
    for a in raw:
        txt = a.get("text_en") if lang == "en" else a.get("text_ar")
        if not txt:
            txt = a.get("text_ar") or a.get("text_en") or ""
        out.append({
            "id": a["id"],
            "ts": a.get("ts", now),
            "kind": a.get("kind", "app_update"),
            "text": txt,
        })
    return sorted(out, key=lambda x: x["ts"], reverse=True)

async def _auto_delete(bot: Bot, chat_id: int, message_id: int, after_seconds: int):
    try:
        await asyncio.sleep(max(0, int(after_seconds)))
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass

# ---------- broadcast ----------
async def broadcast(
    bot: Bot,
    *,
    text_en: Optional[str],
    text_ar: Optional[str],
    kind: str = "app_update",
    delivery: str = "inbox",        # "inbox" (افتراضي: تنبيه + يفتح من الصندوق) أو "push"
    ping_ttl: int = 0,              # حذف رسالة التنبيه بعد n ثواني (0 = لا يحذف)
    active_for: int = 7*24*3600     # بقاء الإشعار نشطًا في الصندوق (افتراضي أسبوع)
) -> Tuple[int, int, int]:
    """
    Returns (sent, skipped, failed)
    - delivery="inbox": يسجّل الإشعار في ACTIVE_FILE ويرسل تنبيهًا مختصرًا بزر فتح.
    - delivery="push":  يرسل النص مباشرة للمستخدمين بلا صندوق.
    """
    cfg = get_config()
    if not cfg.get("enabled", True):
        return (0, 0, 0)

    rl = max(1, int(cfg.get("rate_limit") or 10))
    delay = 1.0 / float(rl)

    # جهّز الإشعار النشط (مرّة واحدة)
    now = int(time.time())
    alert_id = f"a{now}"
    active = _gc_active(_load_active())
    active.append({
        "id": alert_id,
        "ts": now,
        "kind": kind,
        "text_en": text_en,
        "text_ar": text_ar,
        "expires": (now + int(active_for)) if active_for and active_for > 0 else None,
    })
    _save_active(active)

    subs = _load_subscriptions()
    known = _load_known_users()
    recipients = {int(uid) for uid, on in subs.items() if on} or known
    if not recipients:
        return (0, 0, 0)

    sent = skipped = failed = 0

    for uid in recipients:
        lang = _pick_lang(uid)
        body = (text_en if lang == "en" else text_ar) or (text_ar or text_en)
        if not body:
            skipped += 1
            continue
        try:
            if delivery == "push":
                m = await bot.send_message(uid, body)
                if ping_ttl > 0:
                    asyncio.create_task(_auto_delete(bot, uid, m.message_id, ping_ttl))
            else:
                title = "🔔 إشعار جديد" if lang == "ar" else "🔔 New alert"
                open_btn = "فتح الإشعار" if lang == "ar" else "Open alert"
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=open_btn, callback_data=f"inb:open:{alert_id}")],
                    [InlineKeyboardButton(
                        text=("📬 صندوق الإشعارات" if lang == "ar" else "📬 Alerts inbox"),
                        callback_data="inb:back"
                    )]
                ])
                m = await bot.send_message(uid, title, reply_markup=kb)
                if ping_ttl > 0:
                    asyncio.create_task(_auto_delete(bot, uid, m.message_id, ping_ttl))

            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        except Exception:
            failed += 1

        await asyncio.sleep(delay)

    _inc_stats(kind, sent)
    return (sent, skipped, failed)
