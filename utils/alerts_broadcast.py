# utils/alerts_broadcast.py
from __future__ import annotations

import asyncio, json, time, datetime, os, threading
from pathlib import Path
from typing import Dict, Any, Set, Optional, List, Tuple

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from utils.alerts_config import get_config
from utils.paths import BASE

# ─────────────────── مسارات التخزين الدائمة ───────────────────
ALERTS_DIR: Path = BASE / "alerts"
ALERTS_DIR.mkdir(parents=True, exist_ok=True)

STATS_FILE: Path  = ALERTS_DIR / "alerts_stats.json"
SUBS_FILE: Path   = ALERTS_DIR / "alerts_subs.json"
ACTIVE_FILE: Path = ALERTS_DIR / "alerts_active.json"  # [ {id, ts, kind, text_en, text_ar, expires?} ]
USER_LANGS: Path  = ALERTS_DIR / "user_langs.json"

# توافق قديم: لو كانت الملفات داخل /data جذرية أو project root انقلها/اقرأها
LEGACY_DIRS: List[Path] = [
    BASE,                 # /data
    Path("data").resolve() if Path("data").exists() else BASE,  # مشروع قديم
]

_LOCK = threading.Lock()

# ─────────────────── أدوات I/O ذرّية ───────────────────
def _atomic_write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_name(f"{path.name}.{int(time.time()*1000)}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(payload)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
    last_err = None
    for i in range(6):
        try:
            try:
                if path.exists():
                    path.chmod(0o666)
            except Exception:
                pass
            os.replace(tmp, path)
            return
        except Exception as e:
            last_err = e
            time.sleep(0.1 * (i + 1))
    try:
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        finally:
            if last_err:
                raise last_err
            raise

def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw or "null")
    except Exception:
        return None

def _save_json(path: Path, data):
    _atomic_write(path, data)

# ─────────────────── Legacy helpers ───────────────────
def _find_legacy(names: List[str]) -> Optional[Path]:
    for d in LEGACY_DIRS:
        for n in names:
            p = d / n
            try:
                if p.exists():
                    return p
            except Exception:
                continue
    return None

# ─────────────────── مصادر المستلمين ───────────────────
def _load_known_users() -> Set[int]:
    """
    يحاول جمع المستخدمين المعروفين من عدة مصادر قديمة/جديدة:
    - alerts/known_users.json (إن وجد)
    - data/users.json | data/known_users.json | data/user_index.json (توافق قديم)
    البُنى المدعومة: dict مفاتيحه أرقام/سلاسل، أو list لعناصر dict فيها id.
    """
    ids: Set[int] = set()

    # 1) ملف مخصص داخل alerts (إن أحببت تخزين index خاص للإشعارات)
    ku_alerts = ALERTS_DIR / "known_users.json"
    if ku_alerts.exists():
        try:
            data = json.loads(ku_alerts.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in data.keys():
                    if str(k).lstrip("-").isdigit():
                        ids.add(int(k))
            elif isinstance(data, list):
                for u in data:
                    uid = u.get("id") if isinstance(u, dict) else u
                    if str(uid).lstrip("-").isdigit():
                        ids.add(int(uid))
        except Exception:
            pass

    # 2) توافق قديم: ابحث في /data الجذرية
    legacy = _find_legacy(["users.json", "known_users.json", "user_index.json"])
    if legacy:
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # شكل: {"123": {...}, "users":[{id:..}, ...]}
                for k in list(data.keys()):
                    if k == "users" and isinstance(data["users"], list):
                        for u in data["users"]:
                            uid = u.get("id") if isinstance(u, dict) else u
                            if str(uid).lstrip("-").isdigit():
                                ids.add(int(uid))
                    elif str(k).lstrip("-").isdigit():
                        ids.add(int(k))
            elif isinstance(data, list):
                for u in data:
                    uid = u.get("id") if isinstance(u, dict) else u
                    if str(uid).lstrip("-").isdigit():
                        ids.add(int(uid))
        except Exception:
            pass

    return ids

def _load_subscriptions() -> Dict[str, bool]:
    """
    alerts_subs.json: {"12345": true, "67890": false, ...}
    """
    return _load_json(SUBS_FILE) or {}

# ─────────────────── إحصاءات ───────────────────
def _inc_stats(kind: str, n: int):
    stats = _load_json(STATS_FILE) or {}
    now = datetime.date.today()
    wk = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    stats.setdefault(wk, {})
    stats[wk][kind] = int(stats[wk].get(kind, 0)) + int(n)
    _save_json(STATS_FILE, stats)

# ─────────────────── تخزين الإشعارات النشطة ───────────────────
def _load_active() -> List[Dict[str, Any]]:
    return _load_json(ACTIVE_FILE) or []

def _save_active(lst: List[Dict[str, Any]]):
    _save_json(ACTIVE_FILE, lst)

def _gc_active(lst: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now = int(time.time())
    return [a for a in lst if not a.get("expires") or int(a.get("expires", 0)) > now]

def _pick_lang(uid: int) -> str:
    try:
        m = _load_json(USER_LANGS) or {}
        val = m.get(str(uid), "ar")
        return str(val or "ar")
    except Exception:
        return "ar"

# ─────────────────── API: قراءة الصندوق ───────────────────
def get_active_alerts(lang: str) -> List[Dict[str, Any]]:
    """
    تُعيد قائمة الإشعارات النشطة مفلترة حسب الوقت،
    مع نص مُختار للغة المطلوبة.
    """
    now = int(time.time())
    with _LOCK:
        raw = _gc_active(_load_active())
        # في كل قراءة ننظّف الملف إذا لزم
        _save_active(raw)

    out: List[Dict[str, Any]] = []
    for a in raw:
        txt = a.get("text_en") if lang == "en" else a.get("text_ar")
        if not txt:
            txt = a.get("text_ar") or a.get("text_en") or ""
        out.append({
            "id": a.get("id"),
            "ts": int(a.get("ts", now)),
            "kind": a.get("kind", "app_update"),
            "text": txt,
        })
    # الأحدث أولاً
    return sorted(out, key=lambda x: int(x.get("ts", now)), reverse=True)

async def _auto_delete(bot: Bot, chat_id: int, message_id: int, after_seconds: int):
    try:
        await asyncio.sleep(max(0, int(after_seconds)))
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass

# ─────────────────── API: الإرسال ───────────────────
async def broadcast(
    bot: Bot,
    *,
    text_en: Optional[str],
    text_ar: Optional[str],
    kind: str = "app_update",
    delivery: str = "inbox",        # "inbox" (افتراضي: تنبيه + يفتح من الصندوق) أو "push"
    ping_ttl: int = 0,              # حذف رسالة التنبيه بعد n ثوانٍ (0 = لا يحذف)
    active_for: int = 7*24*3600     # بقاء الإشعار نشطًا في الصندوق (افتراضي أسبوع)
) -> Tuple[int, int, int]:
    """
    Returns (sent, skipped, failed)

    • delivery="inbox": يسجّل الإشعار في ACTIVE_FILE ويرسل تنبيهًا مختصرًا بزر فتح.
    • delivery="push":  يرسل النص مباشرة للمستخدمين بلا صندوق.
    """
    cfg = get_config()
    if not cfg.get("enabled", True):
        return (0, 0, 0)

    rl = max(1, int(cfg.get("rate_limit") or 10))  # رسائل/ثانية
    delay = 1.0 / float(rl)

    now = int(time.time())
    alert_id = f"a{now}"

    # سجّل الإشعار في الصندوق (مرة واحدة) بذَرّية + قفل
    if delivery == "inbox":
        with _LOCK:
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

    # لو في اشتراكات فعّالة نستخدمها؛ وإلا ن fallback لكل المعروفين
    recipients: Set[int] = {int(uid) for uid, on in (subs or {}).items() if on} or known
    # إزالة قيم غير صالحة
    recipients = {int(x) for x in recipients if str(x).lstrip("-").isdigit()}

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
                inbox_btn = "📬 صندوق الإشعارات" if lang == "ar" else "📬 Alerts inbox"
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=open_btn, callback_data=f"inb:open:{alert_id}")],
                    [InlineKeyboardButton(text=inbox_btn, callback_data="inb:back")]
                ])
                m = await bot.send_message(uid, title, reply_markup=kb)
                if ping_ttl > 0:
                    asyncio.create_task(_auto_delete(bot, uid, m.message_id, ping_ttl))

            sent += 1

        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        except Exception:
            failed += 1

        # احترام معدل الإرسال
        await asyncio.sleep(delay)

    _inc_stats(kind, sent)
    return (sent, skipped, failed)
