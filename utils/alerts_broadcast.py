from __future__ import annotations

# utils/alerts_broadcast.py


import asyncio, json, time, datetime, os, threading
from pathlib import Path
from typing import Dict, Any, Set, Optional, List, Tuple

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from utils.alerts_config import get_config
from utils.paths import BASE
import random
from utils.alerts_policy import (
    should_push, can_send_by_cap, inc_cap, pass_dedupe, mark_pushed,
    best_send_window_now, jitter_delay
)

from utils.alerts_config import get_config
from typing import Iterable




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


KNOWN_USERS_FILE: Path = ALERTS_DIR / "known_users.json"  # ملف بسيط: {"123": true, ...}

# أعلى الملف بجانب بقية الملفات
PINGS_FILE: Path = ALERTS_DIR / "alerts_pings.json"

def _load_pings() -> Dict[str, Any]:
    return _load_json(PINGS_FILE) or {}

def _save_pings(d: Dict[str, Any]) -> None:
    _save_json(PINGS_FILE, d)

def _register_ping(uid: int, mid: int, aid: str) -> None:
    d = _load_pings()
    arr = d.get(str(uid), [])
    arr.append({"mid": int(mid), "aid": str(aid), "ts": int(time.time())})
    # حد أقصى بسيط للفوضى
    arr = arr[-5:]
    d[str(uid)] = arr
    _save_pings(d)

async def clear_user_pings(bot: Bot, uid: int) -> None:
    """يمسح كل رسائل التنبيه المخزَّنة لهذا المستخدم (لو كانت موجودة)."""
    try:
        d = _load_pings()
        arr = list(d.get(str(uid), []))
        for it in arr:
            mid = int(it.get("mid") or 0)
            if mid:
                try:
                    await bot.delete_message(uid, mid)
                except Exception:
                    pass
        if str(uid) in d:
            del d[str(uid)]
            _save_pings(d)
    except Exception:
        pass

def _load_known_map() -> Dict[str, bool]:
    return _load_json(KNOWN_USERS_FILE) or {}

def _save_known_map(d: Dict[str, bool]) -> None:
    _save_json(KNOWN_USERS_FILE, d)

def track_user(user_id: int, lang: str | None = None) -> None:
    """سجّل المستخدم كمستلم محتمل واشّر لغته للاستخدام لاحقًا."""
    if not str(user_id).lstrip("-").isdigit():
        return
    with _LOCK:
        m = _load_known_map()
        if str(user_id) not in m:
            m[str(user_id)] = True
            _save_known_map(m)
        # اختياري: خزن اللغة
        try:
            langs = _load_json(USER_LANGS) or {}
            if lang:
                langs[str(user_id)] = lang
                _save_json(USER_LANGS, langs)
        except Exception:
            pass

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
# ─────────────────── API: الإرسال ───────────────────
async def broadcast(
    bot: Bot,
    *,
    text_en: Optional[str],
    text_ar: Optional[str],
    kind: str = "app_update",
    delivery: str = "inbox",
    ping_ttl: int = 0,
    active_for: int = 7*24*3600,
    smart_target: bool = True,
    target_segment: str = "all",
    min_last_open_days: int = 0,
    dedupe_key: Optional[str] = None,
    dedupe_window: int = 14*24*3600,
    retry_on_fail: int = 1,
    jitter_ms: int = 200,
    # جديد:
    force_push: bool = False,      # ← افرض Push للجميع
    ignore_quiet: bool = False,    # ← تجاهل ساعات الهدوء
) -> Tuple[int, int, int]:

    """
    Returns (sent, skipped, failed)
    """
    cfg = get_config()
    if not cfg.get("enabled", True):
        return (0, 0, 0)

    # 1) سجّل الإشعار في الصندوق دائماً (قبل أي فحص هدوء)
    now = int(time.time())
    alert_id = f"a{now}"
    if (delivery == "inbox") or smart_target or force_push:
        # نسجله حتى لو push — يظهر في صندوق الإشعارات أيضاً
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

    # 2) ساعات الهدوء — نتجاوزها لو ignore_quiet=True
    quiet_enabled = bool(cfg.get("quiet_enabled", False))
    if quiet_enabled and not ignore_quiet:
        allowed_now, _ = best_send_window_now()
        if not allowed_now:
            # الصندوق سجل مسبقًا؛ تأجيل الإرسال اللحظي
            return (0, 0, 0)

    # 3) اختيار المستلمين
    subs = _load_subscriptions()
    known = _load_known_users()
    recipients: Set[int] = {int(uid) for uid, on in (subs or {}).items() if on} or known
    recipients = {int(x) for x in recipients if str(x).lstrip("-").isdigit()}
    if not recipients:
        return (0, 0, 0)

    from utils.alerts_policy import load_signals
    signals = load_signals()

    def _is_active(u: dict) -> bool:
        last_open = int(u.get("last_open") or 0)
        return (now - last_open) <= (14 * 24 * 3600)

    def _is_dormant(u: dict) -> bool:
        last_open = int(u.get("last_open") or 0)
        return (now - last_open) > (21 * 24 * 3600)

    filtered: List[int] = []
    for uid in recipients:
        u = signals.get(str(uid), {})
        if target_segment == "active" and not _is_active(u):
            continue
        if target_segment == "dormant" and not _is_dormant(u):
            continue
        if min_last_open_days > 0:
            last_open = int(u.get("last_open") or 0)
            if (now - last_open) < (min_last_open_days * 24 * 3600):
                continue
        filtered.append(uid)

    rl = max(1, int(cfg.get("rate_limit") or 10))
    base_delay = 1.0 / float(rl)

    sent = skipped = failed = 0

    for uid in filtered:
        # ✅ عند force_push: نتجاوز الحدّ الأسبوعي ومانع التكرار
        if not force_push:
            if not can_send_by_cap(uid, max_per_week=int(cfg.get("max_per_week") or 2)):
                skipped += 1
                await asyncio.sleep(jitter_delay(base_delay, jitter_ms=jitter_ms))
                continue
            if not pass_dedupe(uid, dedupe_key, window_seconds=dedupe_window):
                skipped += 1
                await asyncio.sleep(jitter_delay(base_delay, jitter_ms=jitter_ms))
                continue

        # لغة ونص
        lang = _pick_lang(uid)
        body = (text_en if lang == "en" else text_ar) or (text_ar or text_en)
        if not body:
            skipped += 1
            await asyncio.sleep(jitter_delay(base_delay, jitter_ms=jitter_ms))
            continue

        # وضع التسليم: force_push يفرض push
        mode = "push" if force_push else (delivery if not smart_target else ("push" if should_push(uid, now=now) else "inbox"))

        # إرسال مع كيبورد يطابق الهاندلرات الموجودة
        attempt = 0
        ok = False
        while attempt <= max(0, int(retry_on_fail)):
            attempt += 1
            try:
                # نصوص الأزرار حسب اللغة
                title_txt  = "🔔 إشعار جديد" if lang == "ar" else "🔔 New alert"
                open_txt   = "فتح الإشعار"   if lang == "ar" else "Open alert"
                inbox_txt  = "📬 الصندوق"     if lang == "ar" else "📬 Inbox"
                ignore_txt = "🙈 تجاهل"      if lang == "ar" else "🙈 Ignore"
                delete_txt = "🗑️ حذف"        if lang == "ar" else "🗑️ Delete"

                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=open_txt,   callback_data=f"ibox:open:{alert_id}:0:a")],
                    [
                        InlineKeyboardButton(text=ignore_txt, callback_data=f"ibox:ignore:{alert_id}:0:a"),
                        InlineKeyboardButton(text=delete_txt, callback_data=f"ibox:delete:{alert_id}:0:a"),
                    ],
                    [InlineKeyboardButton(text=inbox_txt,  callback_data="ibox:list:0:a")],
                ])

                if mode == "push":
                    m = await bot.send_message(uid, body, disable_web_page_preview=True, reply_markup=kb)
                    mark_pushed(uid)
                else:
                    m = await bot.send_message(uid, title_txt, reply_markup=kb)

                _register_ping(uid, m.message_id, alert_id)

                if ping_ttl > 0:
                    asyncio.create_task(_auto_delete(bot, uid, m.message_id, ping_ttl))

                ok = True
                break
            except (TelegramForbiddenError, TelegramBadRequest):
                break
            except Exception:
                await asyncio.sleep(0.5 + random.random())

        if ok:
            # ✅ عند force_push: لا نزيد العداد كي لا يؤثر على الإرسال القادم
            if not force_push:
                inc_cap(uid)
            sent += 1
        else:
            failed += 1

        await asyncio.sleep(jitter_delay(base_delay, jitter_ms=jitter_ms))

    _inc_stats(kind, sent)
    return (sent, skipped, failed)
