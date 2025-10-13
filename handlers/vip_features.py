# handlers/vip_features.py
from __future__ import annotations

import os, asyncio, time, json, datetime as dt, re, logging, random, contextlib
from typing import Optional, Tuple, List, Dict

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from lang import t, get_user_lang

logger = logging.getLogger(__name__)
router = Router(name="vip_features")

# ===================== أدوات ترجمة آمنة (عربي/إنكليزي) =====================
def _lang(uid: int) -> str:
    return get_user_lang(uid) or "en"

def _t_safe(lang: str, key: str, ar_fallback: str | None = None, en_fallback: str | None = None) -> str:
    try:
        s = t(lang, key)
        if isinstance(s, str) and s.strip():
            return s
    except Exception:
        pass
    if ar_fallback is not None or en_fallback is not None:
        return ar_fallback if lang == "ar" else (en_fallback if en_fallback is not None else ar_fallback or key)
    return key

# زر عام للإلغاء والرجوع
CANCEL_CB = "vip:cancel"

# ====================== استيراد وظائف VIP من التخزين =======================
try:
    from utils.vip_store import (
        is_vip, get_vip_meta, extend_vip_days, add_vip, add_vip_seconds,
        remove_vip, normalize_app_id,
        _load_vip_raw, _save_vip_raw
    )
except Exception:
    def is_vip(_): return False
    def get_vip_meta(_): return {}
    def extend_vip_days(_, __): return False
    def add_vip(*args, **kwargs): return None
    def add_vip_seconds(*args, **kwargs): return None
    def remove_vip(*args, **kwargs): return None
    def normalize_app_id(s): return (s or "").strip().lower()
    def _load_vip_raw(): return {"users": {}}
    def _save_vip_raw(d): return None

# ====================== تحقّق من SNAKE / App ID ============================
_SNAKE_ONLY = os.getenv("SNAKE_ONLY", "0").strip() not in ("0", "false", "False", "")
_SNAKE_PATTERNS = [r"com\.snake\.[A-Za-z0-9._\-]{2,60}", r"snake\-[A-Za-z0-9._\-]{2,60}", r"\d{4,10}"]
_SNAKE_RX   = re.compile(r"^(?:%s)$" % "|".join(_SNAKE_PATTERNS))
_GENERIC_RX = re.compile(r"^[A-Za-z0-9._\-]{3,80}$")
def _valid_app_id(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    if _SNAKE_ONLY:
        return bool(_SNAKE_RX.fullmatch(s))
    return bool(_SNAKE_RX.fullmatch(s) or _GENERIC_RX.fullmatch(s))

# ====================== إعدادات العدّاد ======================
VIP_STATUS_REFRESH_SEC = max(1, int(os.getenv("VIP_STATUS_REFRESH_SEC") or os.getenv("VIP_CRON_INTERVAL_SEC", "5")))
VIP_STATUS_MAX_MIN = max(1, int(os.getenv("VIP_STATUS_MAX_MIN", "120")))

# ====================== ملفات التخزين الخفيفة ======================
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)
USER_REQ_FILE = os.path.join(DATA_DIR, "vip_user_requests.json")
REPORT_FILE   = os.path.join(DATA_DIR, "report_sellers.json")
KEYS_FILE     = os.path.join(DATA_DIR, "vip_keys.json")

def _load_json_list(path: str) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception:
        return []

def _save_json_list(path: str, lst: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lst, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def _append_json_list(path: str, item: dict):
    lst = _load_json_list(path)
    lst.append(item)
    _save_json_list(path, lst)

def _find_request(ticket_id: str) -> Optional[dict]:
    for it in _load_json_list(USER_REQ_FILE):
        if it.get("ticket_id") == ticket_id:
            return it
    return None

def _update_request(ticket_id: str, **changes) -> bool:
    lst = _load_json_list(USER_REQ_FILE)
    changed = False
    for it in lst:
        if it.get("ticket_id") == ticket_id:
            it.update(changes)
            changed = True
            break
    if changed: _save_json_list(USER_REQ_FILE, lst)
    return changed

# ---------- Keys storage ----------
def _keys_load() -> dict:
    try:
        with open(KEYS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

def _keys_save(d: dict) -> None:
    os.makedirs(os.path.dirname(KEYS_FILE), exist_ok=True)
    tmp = KEYS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, KEYS_FILE)

def _kid() -> str:
    return f"k{int(time.time())%100000:05d}{random.randint(0, 9999):04d}"

def _keys_for(uid: int) -> list[dict]:
    d = _keys_load()
    arr = d.get(str(uid)) or []
    seen = set()
    for it in arr:
        if "kid" not in it or not it["kid"]:
            nk = _kid()
            while nk in seen:
                nk = _kid()
            it["kid"] = nk
        seen.add(it["kid"])
    d[str(uid)] = arr
    _keys_save(d)
    return arr

def _key_find(uid: int, kid: str) -> Optional[dict]:
    for it in _keys_for(uid):
        if it.get("kid") == kid:
            return it
    return None

def _key_add(uid: int, app_id: str, key_text: str, note: str = "") -> dict:
    d = _keys_load()
    arr = d.get(str(uid)) or []
    item = {
        "kid": _kid(),
        "app_id": normalize_app_id(app_id),
        "key": key_text.strip(),
        "note": note.strip(),
        "created_at": int(time.time())
    }
    arr.append(item)
    d[str(uid)] = arr
    _keys_save(d)
    return item

def _key_update_note(uid: int, kid: str, note: str) -> bool:
    d = _keys_load()
    arr = d.get(str(uid)) or []
    changed = False
    for it in arr:
        if it.get("kid") == kid:
            it["note"] = note.strip()
            changed = True
            break
    if changed:
        d[str(uid)] = arr
        _keys_save(d)
    return changed

def _key_delete(uid: int, kid: str) -> bool:
    d = _keys_load()
    arr = d.get(str(uid)) or []
    new_arr = [it for it in arr if it.get("kid") != kid]
    if len(new_arr) == len(arr):
        return False
    d[str(uid)] = new_arr
    _keys_save(d)
    return True

# ====================== أدوات مساعدة عامة ======================
def _admin_ids() -> list[int]:
    env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
    ids: list[int] = []
    for p in env.split(","):
        p = p.strip()
        if p.isdigit():
            ids.append(int(p))
    return ids or [7360982123]

async def _notify_admins(bot, text: str, *, reply_kb=None, photo_id: str | None = None, doc_id: str | None = None):
    for uid in _admin_ids():
        try:
            if photo_id:
                await bot.send_photo(uid, photo_id, caption=text, reply_markup=reply_kb, parse_mode=ParseMode.HTML)
            elif doc_id:
                await bot.send_document(uid, doc_id, caption=text, reply_markup=reply_kb, parse_mode=ParseMode.HTML)
            else:
                await bot.send_message(uid, text, reply_markup=reply_kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass

def _now_iso() -> str:
    return dt.datetime.utcnow().isoformat() + "Z"

def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

# ====================== تتبّع شاشة الحالة الحية ======================
_LIVE_TASKS: Dict[int, asyncio.Task] = {}      # user_id -> task
_LIVE_MSG_IDS: Dict[int, int] = {}             # user_id -> message_id

async def _stop_live_status(uid: int, *, bot=None, chat_id: int | None = None, delete_msg: bool = False):
    """يلغي حلقة حالة VIP لهذه المستخدم ويحذف رسالتها إن لزم."""
    task = _LIVE_TASKS.pop(uid, None)
    if task and not task.done():
        task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.sleep(0)  # تسليم ليلتقط CancelledError
    mid = _LIVE_MSG_IDS.pop(uid, None)
    if delete_msg and bot and chat_id and mid:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass

# ====================== لوحات الأزرار ======================
def _kb_back_to_vip(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⬅️ " + _t_safe(lang, "vip.back", "رجوع", "Back"),
                                callback_data="vip:open_tools"))
    kb.row(InlineKeyboardButton(text="🏠 " + _t_safe(lang, "vip.back_to_menu", "رجوع للقائمة", "Back to menu"),
                                callback_data="back_to_menu"))
    return kb.as_markup()

def _kb_cancel(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="↩️ " + (_t_safe(lang, "cancel", "إلغاء", "Cancel")),
                                callback_data=CANCEL_CB))
    kb.row(InlineKeyboardButton(text="⬅️ " + _t_safe(lang, "vip.back", "رجوع", "Back"),
                                callback_data="vip:open_tools"))
    return kb.as_markup()

def _kb_vip_tools(lang: str):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⚡ " + _t_safe(lang, "vip.sec.quick", "إجراءات سريعة", "Quick actions"),
                                callback_data="noop"))
    kb.row(
        InlineKeyboardButton(text="📅 " + _t_safe(lang, "vip.tools.status", "حالة الاشتراك", "Status"),
                             callback_data="viptool:status"),
        InlineKeyboardButton(text="🧰 " + _t_safe(lang, "vip.tools.utilities", "أدوات VIP", "Utilities"),
                             callback_data="viptool:utils"),
    )
    kb.row(InlineKeyboardButton(text="💬 " + _t_safe(lang, "vip.tools.priority_support", "دعم فوري", "Priority support"),
                                callback_data="viptool:support"))
    kb.row(InlineKeyboardButton(text="🪪 " + _t_safe(lang, "vip.sec.manage", "إدارة الاشتراك", "Manage"),
                                callback_data="noop"))
    kb.row(
        InlineKeyboardButton(text="🗂 " + _t_safe(lang, "vip.manage_ids", "إدارة المعرفات", "Manage IDs"),
                             callback_data="viptool:manage_ids"),
        InlineKeyboardButton(text="🔁 " + _t_safe(lang, "vip.tools.transfer", "نقل الاشتراك", "Transfer"),
                             callback_data="viptool:transfer"),
    )
    kb.row(
        InlineKeyboardButton(text="💾 " + _t_safe(lang, "vip.keys.save_btn", "حفظ مفتاح/معرّف", "Save key/ID"),
                             callback_data="viptool:savekey"),
        InlineKeyboardButton(text="🔐 " + _t_safe(lang, "vip.keys.my_btn", "مفاتيحي", "My keys"),
                             callback_data="viptool:mykeys"),
    )
    kb.row(InlineKeyboardButton(text="🔁 " + _t_safe(lang, "vip.renew", "تجديد / ترقية", "Renew / Upgrade"),
                                callback_data="viptool:renew"))
    kb.row(InlineKeyboardButton(text="🛡️ " + _t_safe(lang, "vip.sec.safety", "الأمان والدعم", "Safety & support"),
                                callback_data="noop"))
    kb.row(
        InlineKeyboardButton(text="🛡️ " + _t_safe(lang, "vip.security", "حالة الأمان", "Security status"),
                             callback_data="security_status:vip"),
        InlineKeyboardButton(text="🚩 " + _t_safe(lang, "vip.tools.report_seller", "الإبلاغ عن بائع", "Report a seller"),
                             callback_data="viptool:report_seller"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ " + _t_safe(lang, "vip.back_to_menu", "رجوع للقائمة", "Back to menu"),
                                callback_data="back_to_menu"))
    return kb.as_markup()

def _kb_utils(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text="🧹 " + _t_safe(lang, "vip.utils.clean_cache_btn", "تنظيف الكاش", "Clean cache"),
            callback_data="viptool:util:clean_cache"
        ),
        InlineKeyboardButton(
            text="🔍 " + _t_safe(lang, "vip.utils.scan_apps_btn", "فحص التطبيقات", "Scan apps"),
            callback_data="viptool:util:scan_apps"
        ),
    )
    kb.row(
        InlineKeyboardButton(
            text="🛠️ " + _t_safe(lang, "vip.utils.fix_perms_btn", "إصلاح تلقائي", "One-click fix"),
            callback_data="viptool:util:fix_perms"
        ),
        InlineKeyboardButton(
            text="📵 " + _t_safe(lang, "vip.utils.block_updates_btn", "إيقاف التحديثات", "Block updates"),
            callback_data="viptool:util:block_updates"
        ),
    )
    kb.row(
        InlineKeyboardButton(
            text="🆔 " + _t_safe(lang, "vip.utils.temp_id_btn", "مولّد هوية مؤقتة", "Temp ID generator"),
            callback_data="viptool:util:temp_id"
        ),
        InlineKeyboardButton(
            text="📋 " + _t_safe(lang, "vip.utils.device_diag_btn", "تشخيص الجهاز", "Device diagnostics"),
            callback_data="viptool:util:device_diag"
        ),
    )
    kb.row(InlineKeyboardButton(text="⬅️ " + _t_safe(lang, "vip.back", "رجوع", "Back"),
                                callback_data="vip:open_tools"))
    return kb.as_markup()

# ====================== حالة الاشتراك (لايف) ======================
def _fmt_left(secs: int) -> str:
    secs = max(0, int(secs))
    d, r = divmod(secs, 86400); h, r = divmod(r, 3600); m, s = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s or not parts: parts.append(f"{s}s")
    return " ".join(parts)

def _status_text(lang: str, expiry_ts: int | None) -> str:
    now = int(time.time())
    if not isinstance(expiry_ts, int):
        return "👑 " + _t_safe(lang, "vip.tools.status_msg", "حالة اشتراكك:", "Your VIP status:") + "\n" + _t_safe(lang, "vip.status.permanent", "مدى الحياة", "Lifetime")
    left = expiry_ts - now
    if left <= 0:
        return "👑 " + _t_safe(lang, "vip.tools.status_msg", "حالة اشتراكك:", "Your VIP status:") + "\n" + _t_safe(lang, "vip.status.expired", "منتهي", "Expired")
    exp_date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expiry_ts))
    return ("👑 " + _t_safe(lang, "vip.tools.status_msg", "حالة اشتراكك:", "Your VIP status:") +
            f"\n⏳ { _t_safe(lang, 'vip.status.time_left', 'الوقت المتبقي', 'Time left') }: <b>{_fmt_left(left)}</b>" +
            f"\n🗓️ { _t_safe(lang, 'vip.expires_on', 'ينتهي في', 'Expires on') }: <code>{exp_date}</code>")

async def _safe_edit_text(msg, text, **kwargs):
    try:
        return await msg.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return msg
        raise

async def _run_live_status(cb: CallbackQuery):
    """يشغل شاشة الحالة الحية مع تتبّع وإلغاء صحيحين."""
    uid = cb.from_user.id
    lang = _lang(uid)

    # ألغِ أي جلسة حالة سابقة واحذف رسالتها
    await _stop_live_status(uid, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=True)

    meta = get_vip_meta(uid) or {}
    expiry_ts = meta.get("expiry_ts")
    msg = await cb.message.answer(_status_text(lang, expiry_ts),
                                  parse_mode=ParseMode.HTML,
                                  reply_markup=_kb_back_to_vip(lang))

    # سجّل المعرّف والمهمة
    _LIVE_MSG_IDS[uid] = msg.message_id
    # سنجعل هذه الدالة نفسها هي الحلقة؛ نسجّل المهمة الحالية ليمكن إلغاؤها من أزرار الرجوع
    _LIVE_TASKS[uid] = asyncio.current_task()  # type: ignore

    max_loops = (VIP_STATUS_MAX_MIN * 60) // VIP_STATUS_REFRESH_SEC
    loops = 0
    try:
        while True:
            await asyncio.sleep(VIP_STATUS_REFRESH_SEC); loops += 1
            # توقّف إذا أُلغيت المهمة أو تغيّر الرسالة
            if uid not in _LIVE_TASKS or _LIVE_MSG_IDS.get(uid) != msg.message_id:
                break
            if loops >= max_loops:
                break

            if not is_vip(uid):
                try:
                    await _safe_edit_text(msg,
                        "👑 " + _t_safe(lang, "vip.tools.status_msg", "حالة اشتراكك:", "Your VIP status:") +
                        "\n" + _t_safe(lang, "vip.status.not_vip", "لست VIP", "Not VIP"),
                        parse_mode=ParseMode.HTML,
                        reply_markup=_kb_back_to_vip(lang))
                except Exception:
                    pass
                break

            meta = get_vip_meta(uid) or {}
            expiry_ts = meta.get("expiry_ts")
            now = int(time.time())

            if not isinstance(expiry_ts, int):
                try:
                    await _safe_edit_text(msg, _status_text(lang, None),
                        parse_mode=ParseMode.HTML,
                        reply_markup=_kb_back_to_vip(lang))
                except Exception:
                    pass
                break

            left = expiry_ts - now
            if left <= 0:
                try:
                    await _safe_edit_text(msg, _status_text(lang, expiry_ts),
                        parse_mode=ParseMode.HTML,
                        reply_markup=_kb_back_to_vip(lang))
                except Exception:
                    pass
                break

            try:
                await _safe_edit_text(msg, _status_text(lang, expiry_ts),
                    parse_mode=ParseMode.HTML,
                    reply_markup=_kb_back_to_vip(lang))
            except Exception:
                break
    except asyncio.CancelledError:
        # أُلغيت من زر الرجوع
        pass
    finally:
        # نظّف فقط إذا ما زالت هذه الجلسة هي المسجّلة
        if _LIVE_MSG_IDS.get(uid) == msg.message_id:
            _LIVE_MSG_IDS.pop(uid, None)
        _LIVE_TASKS.pop(uid, None)

# ====================== بروفايل VIP (نص + أزرار) ======================
def _vip_profile_text(lang: str, uid: int) -> str:
    meta = get_vip_meta(uid) or {}
    app_id = meta.get("app_id") or "-"
    expiry_ts = meta.get("expiry_ts")
    now = int(time.time())

    if not is_vip(uid):
        status = "🔴 " + _t_safe(lang, "vip.status.not_vip", "غير مُشترك", "Not VIP")
        exp_line = ""
    elif expiry_ts is None:
        status = "🟢 " + _t_safe(lang, "vip.status.active", "نشط", "Active") + " • " + _t_safe(lang, "vip.status.permanent", "مدى الحياة", "Lifetime")
        exp_line = ""
    else:
        left = expiry_ts - now
        if left <= 0:
            status = "⚪ " + _t_safe(lang, "vip.status.expired", "منتهي", "Expired")
            exp_line = ""
        else:
            status = "🟢 " + _t_safe(lang, "vip.status.active", "نشط", "Active") + f" • {_fmt_left(left)}"
            exp_str = time.strftime("%H:%M:%S %d-%m-%Y", time.localtime(expiry_ts))
            exp_line = f"\n🗓️ {_t_safe(lang, 'vip.expires_on', 'تاريخ الانتهاء', 'Expires on')}: <code>{exp_str}</code>"

    keys_count = len(_keys_for(uid) or [])

    title = _t_safe(lang, "vip.profile.title", "الملف الشخصي VIP", "VIP Profile")
    id_lbl = _t_safe(lang, "vip.profile.id", "ID", "ID")
    app_lbl = _t_safe(lang, "vip.profile.app_id", "معرّف التطبيق", "App ID")
    st_lbl  = _t_safe(lang, "vip.profile.status", "الحالة", "Status")
    keys_lbl = _t_safe(lang, "vip.profile.keys", "مفاتيحي", "My keys")

    return (
        f"👑 <b>{title}</b>\n"
        f"—\n"
        f"👤 {id_lbl}: <code>{uid}</code>\n"
        f"🆔 {app_lbl}: <code>{app_id}</code>\n"
        f"📶 {st_lbl}: {status}"
        f"{exp_line}\n"
        f"—\n"
        f"🔐 {keys_lbl}: <b>{keys_count}</b>"
    )

def _kb_profile_actions(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📅 " + _t_safe(lang, "vip.tools.status", "حالة الاشتراك", "Status"),
                                callback_data="viptool:status"),
           InlineKeyboardButton(text="🧰 " + _t_safe(lang, "vip.tools.utilities", "أدوات VIP", "Utilities"),
                                callback_data="viptool:utils"))
    kb.row(InlineKeyboardButton(text="💬 " + _t_safe(lang, "vip.tools.priority_support", "دعم فوري", "Priority support"),
                                callback_data="viptool:support"))
    kb.row(InlineKeyboardButton(text="🗂 " + _t_safe(lang, "vip.manage_ids", "إدارة المعرفات", "Manage IDs"),
                                callback_data="viptool:manage_ids"),
           InlineKeyboardButton(text="🔁 " + _t_safe(lang, "vip.tools.transfer", "نقل الاشتراك", "Transfer"),
                                callback_data="viptool:transfer"))
    kb.row(InlineKeyboardButton(text="💾 " + _t_safe(lang, "vip.keys.save_btn", "حفظ مفتاح/معرّف", "Save key/ID"),
                                callback_data="viptool:savekey"),
           InlineKeyboardButton(text="🔐 " + _t_safe(lang, "vip.keys.my_btn", "مفاتيحي", "My keys"),
                                callback_data="viptool:mykeys"))
    kb.row(InlineKeyboardButton(text="🔁 " + _t_safe(lang, "vip.renew", "تجديد / ترقية", "Renew / Upgrade"),
                                callback_data="viptool:renew"))
    kb.row(InlineKeyboardButton(text="🛡️ " + _t_safe(lang, "vip.security", "حالة الأمان", "Security status"),
                                callback_data="security_status:vip"),
           InlineKeyboardButton(text="🚩 " + _t_safe(lang, "vip.tools.report_seller", "الإبلاغ عن بائع", "Report a seller"),
                                callback_data="viptool:report_seller"))
    kb.row(InlineKeyboardButton(text="🏠 " + _t_safe(lang, "vip.back_to_menu", "رجوع للقائمة", "Back to menu"),
                                callback_data="back_to_menu"))
    return kb.as_markup()

# ====================== فتح اللوحة الرئيسية ======================
@router.callback_query(F.data.in_({"vip:open_tools", "vip_tools"}))
async def open_vip_tools(cb: CallbackQuery):
    # أوقف أي عدّاد حالة لايف
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=True)

    lang = _lang(cb.from_user.id)
    if not is_vip(cb.from_user.id):
        return await cb.answer(
            _t_safe(lang, "vip.bad.not_vip", "هذه الميزة للمشتركين VIP فقط.", "VIP only."),
            show_alert=True
        )
    profile_text = _vip_profile_text(lang, cb.from_user.id)
    try:
        await cb.message.edit_text(profile_text,
                                   reply_markup=_kb_profile_actions(lang),
                                   parse_mode=ParseMode.HTML)
    except TelegramBadRequest:
        await cb.message.answer(profile_text,
                                reply_markup=_kb_profile_actions(lang),
                                parse_mode=ParseMode.HTML)
    await cb.answer()

# ====================== أدوات بسيطة ======================
@router.callback_query(F.data == "viptool:support")
async def vip_support(cb: CallbackQuery):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=True)
    lang = _lang(cb.from_user.id)
    if not is_vip(cb.from_user.id):
        return await cb.answer(_t_safe(lang, "vip.bad.not_vip",
                                       "هذه الميزة للمشتركين VIP فقط.",
                                       "VIP only."),
                               show_alert=True)
    text = "💬 " + _t_safe(lang, "vip.tools.support_msg",
                           "للدعم الفوري تواصل معنا وسيتم الرد بأولوية.",
                           "Contact support; you have priority.")
    await cb.message.edit_text(text,
                               parse_mode=ParseMode.HTML,
                               reply_markup=_kb_back_to_vip(lang))
    await cb.answer()

@router.callback_query(F.data == "viptool:utils")
async def vip_utils(cb: CallbackQuery):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=True)
    lang = _lang(cb.from_user.id)
    if not is_vip(cb.from_user.id):
        return await cb.answer(
            _t_safe(lang, "vip.bad.not_vip", "هذه الميزة للمشتركين VIP فقط.", "VIP only."),
            show_alert=True
        )
    await cb.message.edit_text(
        "🧰 " + _t_safe(lang, "vip.utils.title", "أدوات VIP", "VIP Utilities"),
        reply_markup=_kb_utils(lang)
    )
    await cb.answer()

@router.callback_query(F.data == "viptool:util:fix_perms")
async def util_fix_perms(cb: CallbackQuery):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=False)
    lang = _lang(cb.from_user.id)
    txt = _t_safe(
        lang, "vip.utils.fix_perms_text",
        "اتّبع الخطوات:\n1) أعد تشغيل الهاتف.\n2) امسح كاش التطبيق.\n3) فعّل الأذونات المطلوبة.\n4) سجّل خروج ثم دخول.",
        "Follow these steps:\n1) Reboot the phone.\n2) Clear the app cache.\n3) Ensure required permissions.\n4) Sign out then sign in."
    )
    await cb.message.edit_text("🛠️ " + txt, reply_markup=_kb_utils(lang))
    await cb.answer()

@router.callback_query(F.data == "viptool:util:block_updates")
async def util_block_updates(cb: CallbackQuery):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=False)
    lang = _lang(cb.from_user.id)
    txt = _t_safe(
        lang, "vip.utils.block_updates_text",
        "متجر بلاي > الصورة > الإعدادات > تفضيلات الشبكة > تحديث التطبيقات تلقائيًا > «عدم التحديث».",
        "Play Store > Profile > Settings > Network preferences > Auto-update apps > ‘Don’t auto-update’."
    )
    await cb.message.edit_text("📵 " + txt, reply_markup=_kb_utils(lang))
    await cb.answer()

@router.callback_query(F.data == "viptool:util:temp_id")
async def util_temp_id(cb: CallbackQuery):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=False)
    lang = _lang(cb.from_user.id)
    rid = f"snake-temp-{random.randint(100000, 999999)}"
    await cb.message.edit_text(
        _t_safe(lang, "vip.utils.temp_id_generated",
                "تم إنشاء هوية مؤقتة:\n<code>{id}</code>",
                "Generated a temporary ID:\n<code>{id}</code>").format(id=rid),
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_utils(lang)
    )
    await cb.answer()

@router.callback_query(F.data == "viptool:util:device_diag")
async def util_device_diag(cb: CallbackQuery):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=False)
    lang = _lang(cb.from_user.id)
    txt = _t_safe(
        lang, "vip.utils.device_diag_text",
        "فحص سريع:\n• تحديث النظام؟\n• مساحة كافية؟\n• خدمات Google/Play فعّالة؟\n• الإنترنت مستقر؟\n• لا يوجد VPN/Firewall حاجب؟",
        "Quick checklist:\n• System updated?\n• Enough storage?\n• Google/Play services enabled?\n• Stable internet?\n• No VPN/Firewall blocking?"
    )
    await cb.message.edit_text("📋 " + txt, reply_markup=_kb_utils(lang))
    await cb.answer()

@router.callback_query(F.data == "viptool:status")
async def vip_status(cb: CallbackQuery):
    lang = _lang(cb.from_user.id)
    if not is_vip(cb.from_user.id):
        return await cb.answer(_t_safe(lang, "vip.bad.not_vip", "هذه الميزة للمشتركين VIP فقط.", "VIP only."), show_alert=True)
    # تشغيل شاشة الحالة (تلغي القديمة تلقائيًا)
    await _run_live_status(cb)
    await cb.answer()

@router.callback_query(F.data == "viptool:util:clean_cache")
async def util_clean_cache(cb: CallbackQuery):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=False)
    lang = _lang(cb.from_user.id)
    if not is_vip(cb.from_user.id):
        return await cb.answer(_t_safe(lang, "vip.bad.not_vip", "هذه الميزة للمشتركين VIP فقط.", "VIP only."), show_alert=True)
    await cb.answer(_t_safe(lang, "vip.tools.clean_cache_done", "تم تنظيف الكاش.", "Cache cleaned."), show_alert=True)

@router.callback_query(F.data == "viptool:util:scan_apps")
async def util_scan_apps(cb: CallbackQuery):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=False)
    lang = _lang(cb.from_user.id)
    if not is_vip(cb.from_user.id):
        return await cb.answer(_t_safe(lang, "vip.bad.not_vip", "هذه الميزة للمشتركين VIP فقط.", "VIP only."), show_alert=True)
    await cb.answer(_t_safe(lang, "vip.tools.scan_started", "بدأ الفحص…", "Scan started…"), show_alert=True)

@router.callback_query(F.data == "noop")
async def _noop(cb: CallbackQuery):
    await cb.answer()

# ====================== إدارة المفاتيح (CRUD) ======================
class SaveKeyFSM(StatesGroup):
    ask_app = State()
    ask_key = State()
    ask_note = State()

class EditNoteFSM(StatesGroup):
    ask_note = State()

def _kb_mykeys_list(lang: str, items: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if items:
        for it in items:
            kid = it.get("kid") or _kid()
            title = f"🔑 {it.get('app_id','-')} • {kid[-4:]}"
            kb.row(InlineKeyboardButton(text=title, callback_data=f"mykeys:view:{kid}"))
    kb.row(InlineKeyboardButton(text="➕ " + _t_safe(lang, "vip.keys.add_btn", "إضافة جديد", "Add new"), callback_data="viptool:savekey"))
    kb.row(InlineKeyboardButton(text="⬅️ " + _t_safe(lang, "vip.back", "رجوع", "Back"), callback_data="vip:open_tools"))
    return kb.as_markup()

def _kb_mykey_view(lang: str, kid: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="📝 " + _t_safe(lang, "vip.keys.edit_note", "تعديل الملاحظة", "Edit note"), callback_data=f"mykeys:editnote:{kid}"),
        InlineKeyboardButton(text="🗑 " + _t_safe(lang, "vip.keys.delete", "حذف", "Delete"), callback_data=f"mykeys:del:{kid}")
    )
    kb.row(InlineKeyboardButton(text="⬅️ " + _t_safe(lang, "vip.back", "رجوع", "Back"), callback_data="viptool:mykeys"))
    return kb.as_markup()

@router.callback_query(F.data == "viptool:savekey")
async def savekey_start(cb: CallbackQuery, state: FSMContext):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=True)
    lang = _lang(cb.from_user.id)
    if not is_vip(cb.from_user.id):
        return await cb.answer(_t_safe(lang, "vip.bad.not_vip", "هذه الميزة للمشتركين VIP فقط.", "VIP only."), show_alert=True)
    await state.set_state(SaveKeyFSM.ask_app)
    await cb.message.edit_text("💾 " + _t_safe(lang, "vip.keys.ask_app", "أرسل الآن SNAKE/App ID المراد ربطه بالمفتاح.", "Send the SNAKE/App ID to attach to the key."), reply_markup=_kb_cancel(lang))

@router.message(SaveKeyFSM.ask_app)
async def savekey_app(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)
    app = (msg.text or "").strip()
    if not _valid_app_id(app):
        return await msg.reply(_t_safe(lang, "vip.mi.bad", "المعرّف غير صالح.", "Invalid ID."))
    await state.update_data(app_id=app)
    await state.set_state(SaveKeyFSM.ask_key)
    await msg.reply(_t_safe(lang, "vip.keys.ask_key", "أرسل الآن المفتاح الذي اشتريته.", "Send the key you purchased."), reply_markup=_kb_cancel(lang))

@router.message(SaveKeyFSM.ask_key)
async def savekey_key(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)
    key = (msg.text or "").strip()
    if not key or len(key) < 4:
        return await msg.reply(_t_safe(lang, "vip.keys.bad_key", "مفتاح غير صالح.", "Invalid key."))
    await state.update_data(key=key)
    await state.set_state(SaveKeyFSM.ask_note)
    await msg.reply(_t_safe(lang, "vip.keys.ask_note", "أرسل ملاحظة اختيارية (أو اكتب - لتخطي).", "Send an optional note (or - to skip)."), reply_markup=_kb_cancel(lang))

@router.message(SaveKeyFSM.ask_note)
async def savekey_finish(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)
    data = await state.get_data(); await state.clear()
    note = "" if (msg.text or "").strip() == "-" else (msg.text or "").strip()
    item = _key_add(msg.from_user.id, data["app_id"], data["key"], note)
    created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item["created_at"]))
    txt = (
        _t_safe(lang, "vip.keys.saved", "تم حفظ المفتاح.", "Key saved.") +
        f"\n🆔 <code>{item['app_id']}</code>\n🔑 <code>{item['key']}</code>\n📝 {item.get('note') or '-'}\n⏱ {created}"
    )
    await msg.reply(txt, parse_mode=ParseMode.HTML, reply_markup=_kb_back_to_vip(lang))

@router.callback_query(F.data == "viptool:mykeys")
async def mykeys_list(cb: CallbackQuery):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=True)
    lang = _lang(cb.from_user.id)
    items = _keys_for(cb.from_user.id)
    if not items:
        await cb.message.edit_text("🔐 " + _t_safe(lang, "vip.keys.empty", "لا توجد مفاتيح محفوظة.", "No saved keys."), reply_markup=_kb_mykeys_list(lang, items))
    else:
        lines = ["🔐 " + _t_safe(lang, "vip.keys.list_title", "مفاتيحي", "My keys")]
        for it in items:
            created = time.strftime("%Y-%m-%d", time.localtime(it.get("created_at", int(time.time()))))
            lines.append(f"• <b>{it.get('app_id','-')}</b> — <i>{created}</i>")
        await cb.message.edit_text("\n\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=_kb_mykeys_list(lang, items))
    await cb.answer()

@router.callback_query(F.data.startswith("mykeys:view:"))
async def mykeys_view(cb: CallbackQuery):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=False)
    lang = _lang(cb.from_user.id)
    kid = cb.data.split(":")[2]
    it = _key_find(cb.from_user.id, kid)
    if not it:
        return await cb.answer(_t_safe(lang, "common.not_found", "غير موجود.", "Not found."), show_alert=True)
    created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(it.get("created_at", int(time.time()))))
    txt = (
        "🔑 " + _t_safe(lang, "vip.keys.view_title", "تفاصيل المفتاح", "Key details") +
        f"\n🆔 <code>{it.get('app_id','-')}</code>\n🔑 <code>{it.get('key','-')}</code>\n📝 {it.get('note') or '-'}\n⏱ {created}"
    )
    await cb.message.edit_text(txt, parse_mode=ParseMode.HTML, reply_markup=_kb_mykey_view(lang, kid))
    await cb.answer()

@router.callback_query(F.data.startswith("mykeys:editnote:"))
async def mykeys_editnote_start(cb: CallbackQuery, state: FSMContext):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=False)
    lang = _lang(cb.from_user.id)
    kid = cb.data.split(":")[2]
    if not _key_find(cb.from_user.id, kid):
        return await cb.answer(_t_safe(lang, "common.not_found", "غير موجود.", "Not found."), show_alert=True)
    await state.set_state(EditNoteFSM.ask_note)
    await state.update_data(kid=kid)
    await cb.message.edit_text(_t_safe(lang, "vip.keys.ask_note", "أرسل الملاحظة الجديدة (أو - لمسحها).", "Send new note (or - to clear)."), reply_markup=_kb_cancel(lang))
    await cb.answer()

@router.message(EditNoteFSM.ask_note)
async def mykeys_editnote_apply(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)
    data = await state.get_data(); await state.clear()
    kid = data.get("kid")
    if not kid or not _key_find(msg.from_user.id, kid):
        return await msg.reply(_t_safe(lang, "common.not_found", "غير موجود.", "Not found."))
    note = "" if (msg.text or "").strip() == "-" else (msg.text or "").strip()
    _key_update_note(msg.from_user.id, kid, note)
    await msg.reply(_t_safe(lang, "vip.keys.note_updated", "تم تحديث الملاحظة.", "Note updated."), reply_markup=_kb_mykey_view(lang, kid))

@router.callback_query(F.data.startswith("mykeys:del:"))
async def mykeys_del_confirm(cb: CallbackQuery):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=False)
    lang = _lang(cb.from_user.id)
    kid = cb.data.split(":")[2]
    if not _key_find(cb.from_user.id, kid):
        return await cb.answer(_t_safe(lang, "common.not_found", "غير موجود.", "Not found."), show_alert=True)
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ " + _t_safe(lang, "confirm", "تأكيد", "Confirm"), callback_data=f"mykeys:delc:{kid}"),
        InlineKeyboardButton(text="❌ " + _t_safe(lang, "cancel", "إلغاء", "Cancel"), callback_data="viptool:mykeys"),
    )
    await cb.message.edit_text(_t_safe(lang, "vip.keys.delete_confirm", "هل تريد حذف هذا المفتاح؟", "Delete this key?"), reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data.startswith("mykeys:delc:"))
async def mykeys_del_apply(cb: CallbackQuery):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=False)
    lang = _lang(cb.from_user.id)
    kid = cb.data.split(":")[2]
    ok = _key_delete(cb.from_user.id, kid)
    if not ok:
        return await cb.answer(_t_safe(lang, "common.not_found", "غير موجود.", "Not found."), show_alert=True)
    await cb.message.edit_text(_t_safe(lang, "vip.keys.deleted", "تم الحذف.", "Deleted."), reply_markup=_kb_mykeys_list(lang, _keys_for(cb.from_user.id)))
    await cb.answer()

# إلغاء أي تدفق
@router.callback_query(F.data == CANCEL_CB)
async def cancel_any(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=True)
    lang = _lang(cb.from_user.id)
    await cb.message.edit_text(_t_safe(lang, "cancelled", "تم الإلغاء.", "Cancelled."), reply_markup=_kb_vip_tools(lang))
    await cb.answer()

# إمساك زر "رجوع للقائمة" لإلغاء العدّاد قبل أن يعدّل الرسالة لاحقاً
@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_cancel_loop(cb: CallbackQuery):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=True)
    # لا نعدّل الرسالة هنا؛ نترك فتح القائمة لمعالجتك الرئيسية
    await cb.answer()

# ====================== نماذج تفاعلية (Manage/Transfer/Renew) ======================
def _extract_proof(msg: Message) -> tuple[Optional[str], Optional[str]]:
    if msg.photo:
        return msg.photo[-1].file_id, None
    if msg.document:
        return None, msg.document.file_id
    return None, None

def _admin_req_kb(req_type: str, ticket_id: str, user_id: int):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t_safe("ar", "approve", "✅ موافقة", "✅ Approve"), callback_data=f"req:approve:{req_type}:{ticket_id}:{user_id}"),
        InlineKeyboardButton(text=_t_safe("ar", "reject", "❌ رفض", "❌ Reject"),   callback_data=f"req:reject:{req_type}:{ticket_id}:{user_id}")
    )
    kb.row(InlineKeyboardButton(text="👤 Open chat", url=f"tg://user?id={user_id}"))
    return kb.as_markup()

class ManageIdFSM(StatesGroup):
    ask_seller = State()
    ask_pay_method = State()
    ask_amount = State()
    ask_currency = State()
    ask_date = State()
    ask_order = State()
    ask_new = State()
    ask_device = State()
    ask_proof = State()
    ask_contact = State()
    ask_reason = State()

@router.callback_query(F.data == "viptool:manage_ids")
async def manage_ids_start(cb: CallbackQuery, state: FSMContext):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=True)
    lang = _lang(cb.from_user.id)
    if not is_vip(cb.from_user.id):
        return await cb.answer(_t_safe(lang, "vip.bad.not_vip", "هذه الميزة للمشتركين VIP فقط.", "VIP only."), show_alert=True)
    await state.clear()
    await state.set_state(ManageIdFSM.ask_seller)
    await cb.message.edit_text("🗂 " + _t_safe(lang, "vip.common.ask_seller", "أرسل @اسم مستخدم التلغرام للبائع.", "Send seller @username."), reply_markup=_kb_cancel(lang))
    await cb.answer()


@router.message(ManageIdFSM.ask_seller)
async def mi_seller(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)

    raw = (msg.text or "").strip()
    if not raw:
        return await msg.reply(_t_safe(lang, "vip.common.bad_seller", "الاسم/المعرف غير صالح.", "Invalid seller."))

    # قبول @username أو t.me/username أو رقم (مع أو بدون +)
    s = raw

    # لو أرسل رابط t.me/username نزّل اليوزر منه
    m = re.match(r"^(?:https?://)?t\.me/(@?[A-Za-z0-9_]{3,})/?$", s, re.IGNORECASE)
    if m:
        s = m.group(1)

    # حالات القبول
    is_username = bool(re.fullmatch(r"@?[A-Za-z0-9_]{3,}", s))
    # إزالة + إن وُجدت، وقبول أرقام بطول >= 3 (عدّل الطول لو تحب)
    num = s.lstrip("+")
    is_numeric = num.isdigit() and len(num) >= 3

    if not (is_username or is_numeric):
        return await msg.reply(_t_safe(lang, "vip.common.bad_seller", "الاسم/المعرف غير صالح.", "Invalid seller."))

    # تطبيع التخزين:
    # - لو يوزر: خزّنه بصيغة تبدأ بـ @
    # - لو رقم: خزّنه كأرقام فقط (بدون +)
    if is_numeric:
        seller_val = num
    else:
        seller_val = s if s.startswith("@") else f"@{s}"

    await state.update_data(seller=seller_val)
    await state.set_state(ManageIdFSM.ask_pay_method)
    await msg.reply(_t_safe(lang, "vip.common.ask_pay_method", "طريقة الدفع؟", "Payment method?"))

@router.message(ManageIdFSM.ask_pay_method)
async def mi_pay_method(msg: Message, state: FSMContext):
    await state.update_data(pay_method=(msg.text or "").strip())
    await state.set_state(ManageIdFSM.ask_amount)
    lang = _lang(msg.from_user.id)
    await msg.reply(_t_safe(lang, "vip.common.ask_amount", "المبلغ المدفوع؟", "Amount paid?"))

@router.message(ManageIdFSM.ask_amount)
async def mi_amount(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)
    amount = (msg.text or "").strip()
    if not re.fullmatch(r"\d+(\.\d{1,2})?", amount):
        return await msg.reply(_t_safe(lang, "vip.common.bad_amount", "أدخل رقمًا صحيحًا.", "Enter a valid number."))
    await state.update_data(amount=amount)
    await state.set_state(ManageIdFSM.ask_currency)
    await msg.reply(_t_safe(lang, "vip.common.ask_currency", "العملة؟", "Currency?"))

@router.message(ManageIdFSM.ask_currency)
async def mi_currency(msg: Message, state: FSMContext):
    await state.update_data(currency=(msg.text or "").strip().upper())
    await state.set_state(ManageIdFSM.ask_date)
    lang = _lang(msg.from_user.id)
    await msg.reply(_t_safe(lang, "vip.common.ask_date", "تاريخ الشراء؟", "Purchase date?"))

@router.message(ManageIdFSM.ask_date)
async def mi_date(msg: Message, state: FSMContext):
    await state.update_data(purchase_date=(msg.text or "").strip())
    await state.set_state(ManageIdFSM.ask_order)
    lang = _lang(msg.from_user.id)
    await msg.reply(_t_safe(lang, "vip.common.ask_order", "رقم الطلب/الإيصال؟", "Order/reference?"))

@router.message(ManageIdFSM.ask_order)
async def mi_order(msg: Message, state: FSMContext):
    await state.update_data(order_ref=(msg.text or "").strip())
    await state.set_state(ManageIdFSM.ask_new)
    lang = _lang(msg.from_user.id)
    await msg.reply(_t_safe(lang, "vip.mi.ask_new", "أرسل الآن SNAKE ID الجديد.", "Send the new SNAKE ID."))

@router.message(ManageIdFSM.ask_new)
async def mi_new_id(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)
    new_id = (msg.text or "").strip()
    if not _valid_app_id(new_id):
        return await msg.reply(_t_safe(lang, "vip.mi.bad", "المعرّف غير صالح.", "Invalid ID."))
    await state.update_data(new_app_id=new_id)
    await state.set_state(ManageIdFSM.ask_device)
    await msg.reply(_t_safe(lang, "vip.common.ask_device", "اكتب طراز جهازك.", "Your device model."))

@router.message(ManageIdFSM.ask_device)
async def mi_device(msg: Message, state: FSMContext):
    await state.update_data(device=(msg.text or "").strip())
    await state.set_state(ManageIdFSM.ask_proof)
    lang = _lang(msg.from_user.id)
    await msg.reply(_t_safe(lang, "vip.common.ask_proof", "أرسل صورة/ملف لإثبات الدفع.", "Send photo/document as proof."))

@router.message(ManageIdFSM.ask_proof)
async def mi_proof(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)
    photo_id, doc_id = (None, None)
    if msg.photo:
        photo_id = msg.photo[-1].file_id
    elif msg.document:
        doc_id = msg.document.file_id
    else:
        return await msg.reply(_t_safe(lang, "vip.common.send_proof", "أرسل الإثبات كصورة أو ملف.", "Please send proof as photo or document."))
    await state.update_data(proof_photo=photo_id, proof_doc=doc_id)
    await state.set_state(ManageIdFSM.ask_contact)
    await msg.reply(_t_safe(lang, "vip.common.ask_contact", "أرسل وسيلة تواصل بديلة (اختياري).", "Send alternative contact (optional)."))

@router.message(ManageIdFSM.ask_contact)
async def mi_contact(msg: Message, state: FSMContext):
    await state.update_data(contact=(msg.text or "").strip())
    await state.set_state(ManageIdFSM.ask_reason)
    lang = _lang(msg.from_user.id)
    await msg.reply(_t_safe(lang, "vip.mi.ask_note", "ملاحظة إضافية (اختياري).", "Additional note (optional)."))

@router.message(ManageIdFSM.ask_reason)
async def mi_finish(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)
    data = await state.get_data(); await state.clear()
    meta = get_vip_meta(msg.from_user.id) or {}
    old_id = meta.get("app_id") or "-"
    ticket = f"MI-{msg.from_user.id}-{int(time.time())%1000000:06d}"

    item = {
        "status": "open", "type": "manage_id", "ticket_id": ticket, "when": _now_iso(),
        "user": msg.from_user.id,
        "seller": data.get("seller"),
        "pay_method": data.get("pay_method"),
        "amount": data.get("amount"), "currency": data.get("currency"),
        "purchase_date": data.get("purchase_date"), "order_ref": data.get("order_ref"),
        "old_app_id": old_id, "new_app_id": data.get("new_app_id"),
        "device": data.get("device"),
        "contact": data.get("contact"),
        "note": (msg.text or "").strip(),
        "proof_photo": data.get("proof_photo"), "proof_doc": data.get("proof_doc"),
    }
    _append_json_list(USER_REQ_FILE, item)

    await msg.reply(_t_safe(lang, "vip.mi.done", "تم إرسال طلبك.\nالتذكرة: {ticket_id}\nالمعرّف الجديد: {new_app_id}", "Your request was submitted.\nTicket: {ticket_id}\nNew ID: {new_app_id}").format(ticket_id=ticket, new_app_id=item["new_app_id"]), parse_mode=ParseMode.HTML, reply_markup=_kb_back_to_vip(lang))

    admin = (
        "🗂 <b>طلب نقل اشتراط ثعبان</b>\n"
        f"🎫 Ticket: <code>{ticket}</code>\n"
        f"👤 User: <code>{msg.from_user.id}</code>\n"
        f"• Seller: {item['seller']}\n"
        f"• Payment: {item['pay_method']} | {item['amount']} {item['currency']} | {item['purchase_date']} | Ref: {item['order_ref']}\n"
        f"• Old App ID: <code>{old_id}</code>\n"
        f"• New App ID: <code>{item['new_app_id']}</code>\n"
        f"• Device: {item['device'] or '-'}\n"
        f"• Contact: {item['contact'] or '-'}\n"
        f"• Reason: {item['note'] or '-'}\n"
        f"• When: <code>{_now_str()}</code>"
    )
    await _notify_admins(msg.bot, admin, reply_kb=_admin_req_kb("manage_id", ticket, msg.from_user.id), photo_id=item["proof_photo"], doc_id=item["proof_doc"])

# ---- نقل الاشتراك ----
class TransferFSM(StatesGroup):
    ask_seller = State()
    ask_target = State()
    ask_appid = State()
    ask_proof = State()
    ask_note = State()

@router.callback_query(F.data == "viptool:transfer")
async def transfer_start(cb: CallbackQuery, state: FSMContext):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=True)
    lang = _lang(cb.from_user.id)
    if not is_vip(cb.from_user.id):
        return await cb.answer(_t_safe(lang, "vip.bad.not_vip", "هذه الميزة للمشتركين VIP فقط.", "VIP only."), show_alert=True)
    await state.set_state(TransferFSM.ask_seller)
    await cb.message.edit_text("🔁 " + _t_safe(lang, "vip.common.ask_seller", "أرسل @اسم مستخدم التلغرام للبائع.", "Send seller @username."), reply_markup=_kb_cancel(lang))
    await cb.answer()

@router.message(TransferFSM.ask_seller)
async def transfer_seller(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)
    handle = (msg.text or "").strip()
    if not handle.startswith("@") or len(handle) < 3:
        return await msg.reply(_t_safe(lang, "vip.common.bad_seller", "الاسم غير صالح.", "Invalid seller."))
    await state.update_data(seller=handle)
    await state.set_state(TransferFSM.ask_target)
    await msg.reply(_t_safe(lang, "vip.tx.ask_target", "أرسل ID الرقمي أو @username أو رابط t.me للهدف.", "Send target numeric ID or @username or t.me link."))

@router.message(TransferFSM.ask_target)
async def transfer_target(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)
    raw = (msg.text or "").strip()
    if not (raw.isdigit() or raw.startswith("@") or "t.me/" in raw):
        return await msg.reply(_t_safe(lang, "vip.tx.bad_user", "الهدف غير صالح.", "Invalid target."))
    await state.update_data(target=raw)
    await state.set_state(TransferFSM.ask_appid)
    await msg.reply(_t_safe(lang, "vip.tx.ask_appid", "أرسل SNAKE/App ID الجديد للهدف.", "Send the new SNAKE/App ID for the target."))

@router.message(TransferFSM.ask_appid)
async def transfer_appid(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)
    app_id = (msg.text or "").strip()
    if not _valid_app_id(app_id):
        return await msg.reply(_t_safe(lang, "vip.tx.bad_appid", "المعرّف غير صالح.", "Invalid ID."))
    await state.update_data(new_app_id=app_id)
    await state.set_state(TransferFSM.ask_proof)
    await msg.reply(_t_safe(lang, "vip.common.ask_proof", "أرسل صورة/ملف لإثبات العملية.", "Send photo/document as proof."))

@router.message(TransferFSM.ask_proof)
async def transfer_proof(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)
    photo_id, doc_id = (None, None)
    if msg.photo:
        photo_id = msg.photo[-1].file_id
    elif msg.document:
        doc_id = msg.document.file_id
    else:
        return await msg.reply(_t_safe(lang, "vip.common.send_proof", "أرسل الإثبات كصورة أو ملف.", "Please send proof as photo or document."))
    await state.update_data(proof_photo=photo_id, proof_doc=doc_id)
    await state.set_state(TransferFSM.ask_note)
    await msg.reply(_t_safe(lang, "vip.tx.ask_note", "ملاحظة إضافية (اختياري).", "Additional note (optional)."))

@router.message(TransferFSM.ask_note)
async def transfer_finish(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)
    data = await state.get_data(); await state.clear()
    meta = get_vip_meta(msg.from_user.id) or {}
    old_id = meta.get("app_id") or "-"
    ticket = f"TR-{msg.from_user.id}-{int(time.time())%1000000:06d}"

    item = {
        "status": "open",
        "type": "transfer",
        "ticket_id": ticket,
        "when": _now_iso(),
        "user": msg.from_user.id,
        "seller": data.get("seller"),
        "target": data.get("target"),
        "old_app_id": old_id,
        "new_app_id": data.get("new_app_id"),
        "note": (msg.text or "").strip(),
        "proof_photo": data.get("proof_photo"),
        "proof_doc": data.get("proof_doc")
    }
    _append_json_list(USER_REQ_FILE, item)

    await msg.reply(_t_safe(lang, "vip.tx.done", "تم إرسال طلب النقل.\nالتذكرة: {ticket_id}", "Transfer request submitted.\nTicket: {ticket_id}").format(ticket_id=ticket), parse_mode=ParseMode.HTML, reply_markup=_kb_back_to_vip(lang))

    admin_text = (
        "🔁 <b>طلب نقل لوحه الى جهاز اخر</b>\n"
        f"🎫 Ticket: <code>{ticket}</code>\n"
        f"👤 From User: <code>{msg.from_user.id}</code>\n"
        f"• Seller: {item['seller']}\n"
        f"➡️ Target: <code>{item['target']}</code>\n"
        f"• Old App ID: <code>{old_id}</code>\n"
        f"• New App ID: <code>{item['new_app_id']}</code>\n"
        f"• Note: {item['note'] or '-'}\n"
        f"• When: <code>{_now_str()}</code>"
    )
    await _notify_admins(msg.bot, admin_text, reply_kb=_admin_req_kb("transfer", ticket, msg.from_user.id), photo_id=item["proof_photo"], doc_id=item["proof_doc"])

# ---- تجديد / ترقية → المورّدون الموثوقون ----
@router.callback_query(F.data == "viptool:renew")
async def renew_redirect(cb: CallbackQuery):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=False)
    lang = _lang(cb.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🏷️ " + _t_safe(lang, "btn_trusted_suppliers", "الموردون الموثوقون", "Trusted suppliers"), callback_data="trusted_suppliers"))
    kb.row(InlineKeyboardButton(text="⬅️ " + _t_safe(lang, "vip.back", "رجوع", "Back"), callback_data="vip:open_tools"))
    await cb.message.edit_text(_t_safe(lang, "vip.rn.redirect", "للتجديد أو الترقية، اختر بائعًا موثوقًا من القائمة:", "To renew/upgrade, choose a trusted reseller:"), reply_markup=kb.as_markup())
    await cb.answer()

# ====================== تطبيق قرارات الأدمن (موافقة/رفض) ======================
def _apply_manage_id(uid: int, new_app_id: str) -> bool:
    d = _load_vip_raw()
    users = d.get("users") or {}
    meta = users.get(str(uid))
    if not meta:
        return False
    meta["app_id"] = normalize_app_id(new_app_id)
    users[str(uid)] = meta
    d["users"] = users
    _save_vip_raw(d)
    return True

def _apply_transfer(uid: int, target_raw: str, new_app_id: str) -> bool:
    if not str(target_raw).isdigit():
        return False
    target_uid = int(str(target_raw))
    d = _load_vip_raw()
    users = d.get("users") or {}
    src = users.get(str(uid))
    if not src:
        return False
    now = int(time.time())
    exp = src.get("expiry_ts")
    if exp is None:
        add_vip(target_uid, new_app_id, added_by=uid, days=None)
    else:
        try:
            left = max(1, int(exp) - now)
        except Exception:
            left = 30 * 86400
        add_vip_seconds(target_uid, new_app_id, seconds=left, added_by=uid)
    remove_vip(uid)
    return True

@router.callback_query(F.data.startswith("req:approve:"))
async def req_approve(cb: CallbackQuery):
    try:
        _, _, req_type, ticket_id, uid_s = cb.data.split(":", 4)
        uid = int(uid_s)
    except Exception:
        lang = _lang(cb.from_user.id)
        return await cb.answer(_t_safe(lang, "common.bad_payload", "حمولة غير صالحة.", "Bad payload."), show_alert=True)

    lang_u = _lang(uid)
    req = _find_request(ticket_id)
    if not req:
        return await cb.answer(_t_safe(lang_u, "common.not_found", "غير موجود.", "Not found."), show_alert=True)
    if req.get("status") != "open":
        return await cb.answer(_t_safe(lang_u, "common.already_processed", "تمت معالجته مسبقاً.", "Already processed."), show_alert=True)

    applied = False
    try:
        if req_type == "manage_id":
            applied = _apply_manage_id(uid, req.get("new_app_id", ""))
        elif req_type == "transfer":
            applied = _apply_transfer(uid, req.get("target", ""), req.get("new_app_id", ""))
        elif req_type == "renew":
            days = int(req.get("days") or 0)
            if days > 0:
                applied = extend_vip_days(uid, days)
    except Exception as e:
        logger.exception("apply failed: %s", e)

    _update_request(ticket_id, status="approved", approved_by=cb.from_user.id, approved_at=_now_iso(), applied=applied)

    try:
        await cb.bot.send_message(uid, _t_safe(lang_u, "vip.req.approved", "✅ تم قبول طلبك.", "✅ Your request was approved."), parse_mode=ParseMode.HTML)
    except Exception:
        pass

    await cb.answer(_t_safe(lang_u, "common.approved", "تمت الموافقة.", "Approved."))
    try:
        await cb.message.edit_text(cb.message.html_text + "\n\n✅ <b>Approved.</b>", parse_mode=ParseMode.HTML)
    except Exception:
        pass

@router.callback_query(F.data.startswith("req:reject:"))
async def req_reject(cb: CallbackQuery):
    try:
        _, _, req_type, ticket_id, uid_s = cb.data.split(":", 4)
        uid = int(uid_s)
    except Exception:
        lang = _lang(cb.from_user.id)
        return await cb.answer(_t_safe(lang, "common.bad_payload", "حمولة غير صالحة.", "Bad payload."), show_alert=True)

    lang_u = _lang(uid)
    req = _find_request(ticket_id)
    if not req:
        return await cb.answer(_t_safe(lang_u, "common.not_found", "غير موجود.", "Not found."), show_alert=True)
    if req.get("status") != "open":
        return await cb.answer(_t_safe(lang_u, "common.already_processed", "تمت معالجته مسبقاً.", "Already processed."), show_alert=True)

    _update_request(ticket_id, status="rejected", rejected_by=cb.from_user.id, rejected_at=_now_iso())

    try:
        await cb.bot.send_message(uid, _t_safe(lang_u, "vip.req.rejected", "❌ تم رفض طلبك.", "❌ Your request was rejected."), parse_mode=ParseMode.HTML)
    except Exception:
        pass

    await cb.answer(_t_safe(lang_u, "common.rejected", "تم الرفض.", "Rejected."))
    try:
        await cb.message.edit_text(cb.message.html_text + "\n\n❌ <b>Rejected.</b>", parse_mode=ParseMode.HTML)
    except Exception:
        pass

# ====================== الإبلاغ عن بائع ======================
class ReportSeller(StatesGroup):
    seller = State()
    reason = State()

class AdminReplyFSM(StatesGroup):
    waiting = State()

def _is_admin(uid: int) -> bool:
    return uid in _admin_ids()

@router.callback_query(F.data.in_({"viptool:report_seller", "report_seller:start"}))
async def report_seller_start(cb: CallbackQuery, state: FSMContext):
    await _stop_live_status(cb.from_user.id, bot=cb.bot, chat_id=cb.message.chat.id, delete_msg=True)
    lang = _lang(cb.from_user.id)
    if not (os.getenv("ALLOW_REPORT_SELLER_NON_VIP") == "1" or is_vip(cb.from_user.id)):
        return await cb.answer(_t_safe(lang, "vip.bad.not_vip", "هذه الميزة للمشتركين VIP فقط.", "VIP only."), show_alert=True)
    await state.clear()
    await state.set_state(ReportSeller.seller)
    await cb.message.edit_text("🚩 " + _t_safe(lang, "report.seller.ask_user", "أرسل @اسم مستخدم البائع.", "Send seller @username."), reply_markup=_kb_cancel(lang))
    await cb.answer()

@router.message(ReportSeller.seller)
async def report_seller_got_user(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)
    handle = (msg.text or "").strip()
    if not handle.startswith("@") or len(handle) < 3:
        return await msg.reply(_t_safe(lang, "report.seller.bad_user", "اسم غير صالح.", "Invalid username."))
    await state.update_data(seller=handle)
    await state.set_state(ReportSeller.reason)
    await msg.reply(_t_safe(lang, "report.seller.ask_reason", "اذكر السبب بالتفصيل.", "Describe the reason."))

@router.message(ReportSeller.reason)
async def report_seller_finish(msg: Message, state: FSMContext):
    lang = _lang(msg.from_user.id)
    data = await state.get_data(); seller = data.get("seller"); reason = (msg.text or "").strip()
    u = msg.from_user; ticket_id = f"RS{int(time.time())}{u.id%10000:04d}"; now_iso = _now_iso()
    item = {
        "ticket_id": ticket_id, "status": "open", "type": "report_seller", "when": now_iso,
        "chat_id": msg.chat.id, "message_id": msg.message_id,
        "seller": seller, "reason": reason,
        "reporter": {"id": u.id, "username": (u.username and f"@{u.username}") or None,
                     "first_name": u.first_name, "last_name": u.last_name,
                     "lang": getattr(u, "language_code", None), "link": f"tg://user?id={u.id}"},
        "admin_reply": None
    }
    _append_json_list(REPORT_FILE, item); await state.clear()

    you = item["reporter"]
    confirm = (_t_safe(
        lang, "report.confirm",
        "✅ تم استلام بلاغك.\n🎫 رقم التذكرة: <code>{ticket}</code>\n👤 بياناتك: ID=<code>{uid}</code>{uname}\n🚩 البائع: <b>{seller}</b>\n📝 السبب: {reason}\n\n📩 تأكد أن رسائلك الخاصة مفعّلة.",
        "✅ Report received.\n🎫 Ticket: <code>{ticket}</code>\n👤 You: ID=<code>{uid}</code>{uname}\n🚩 Seller: <b>{seller}</b>\n📝 Reason: {reason}\n\n📩 Ensure your private messages are open."
    ).format(
        ticket=ticket_id,
        uid=you['id'],
        uname=((' | ' + you['username']) if you['username'] else ''),
        seller=seller,
        reason=reason or '-'
    ))
    await msg.reply(confirm, parse_mode=ParseMode.HTML, reply_markup=_kb_back_to_vip(lang))

    admin_text = (
        f"🚩 <b>{_t_safe(lang, 'report.admin.title', 'بلاغ بائع', 'Seller Report')}</b>\n"
        f"🎫 {_t_safe(lang, 'ticket', 'تذكرة', 'Ticket')}: <code>{ticket_id}</code>\n"
        f"• {_t_safe(lang, 'report.admin.seller', 'البائع', 'Seller')}: <b>{seller}</b>\n"
        f"• {_t_safe(lang, 'report.admin.reason', 'السبب', 'Reason')}: {reason or '-'}\n"
        "—\n"
        f"👤 {_t_safe(lang, 'report.admin.from', 'من', 'From')}: <code>{you['id']}</code>{(' | ' + you['username']) if you['username'] else ''}\n"
        f"• {_t_safe(lang, 'report.admin.name', 'الاسم', 'Name')}: {you['first_name'] or ''} {you['last_name'] or ''}\n"
        f"• {_t_safe(lang, 'report.admin.link', 'الرابط', 'Link')}: "
        f"<a href='{you['link']}'>{_t_safe(lang, 'report.admin.open_chat', 'فتح المحادثة', 'Open chat')}</a>\n"
        f"• {_t_safe(lang, 'report.admin.lang', 'اللغة', 'Language')}: {you['lang'] or '-'}\n"
        f"• {_t_safe(lang, 'report.admin.when', 'الوقت', 'When')}: <code>{now_iso}</code>"
    )
    await _notify_admins(msg.bot, admin_text)


@router.callback_query(F.data.startswith("rs:reply:"))
async def rs_admin_reply_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in _admin_ids():
        lang = _lang(cb.from_user.id)
        return await cb.answer(_t_safe(lang, "sec.admin.only_admin", "للمشرفين فقط.", "Admins only."), show_alert=True)
    try:
        _, _, ticket_id, uid_str = cb.data.split(":", 3); target_uid = int(uid_str)
    except Exception:
        lang = _lang(cb.from_user.id)
        return await cb.answer(_t_safe(lang, "common.bad_payload", "حمولة غير صالحة.", "Bad payload."), show_alert=True)
    await state.set_state(AdminReplyFSM.waiting)
    await state.update_data(rs_ticket=ticket_id, rs_uid=target_uid, rs_admin=cb.from_user.id)
    await cb.message.edit_text(f"✍️ {_t_safe(_lang(cb.from_user.id),'reply.write','اكتب الرد','Write reply')} <code>{target_uid}</code>\n🎫 {_t_safe(_lang(cb.from_user.id),'ticket','تذكرة','Ticket')}: <code>{ticket_id}</code>", parse_mode=ParseMode.HTML)
    await cb.answer()

@router.message(AdminReplyFSM.waiting)
async def rs_admin_reply_send(msg: Message, state: FSMContext):
    data = await state.get_data(); await state.clear()
    ticket_id = data.get("rs_ticket"); target_uid = int(data.get("rs_uid", 0))
    if not ticket_id or not target_uid: return await msg.reply("…")
    admin_text = (msg.text or "").strip()
    if not admin_text: return await msg.reply("…")
    try:
        await msg.bot.send_message(target_uid, f"📮 <b>Support reply</b>\n🎫 Ticket: <code>{ticket_id}</code>\n—\n{admin_text}", parse_mode=ParseMode.HTML)
        await msg.reply("✅ Sent.")
    except Exception:
        await msg.reply("⚠️ Failed to send (user PMs closed).")

@router.callback_query(F.data.startswith("rs:resolve:"))
async def rs_admin_resolve(cb: CallbackQuery):
    if cb.from_user.id not in _admin_ids():
        lang = _lang(cb.from_user.id)
        return await cb.answer(_t_safe(lang, "sec.admin.only_admin", "للمشرفين فقط.", "Admins only."), show_alert=True)
    await cb.answer("OK")
