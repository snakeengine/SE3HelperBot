# handlers/security_status.py
from __future__ import annotations

import os, json, datetime, logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from lang import t, get_user_lang

# دعم المنطقة الزمنية (Python 3.9+). في حال عدم توفرها نستخدم تعويض +3
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None

router = Router()

# ========= إعدادات عامة / أدمن =========
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def L(user_id: int) -> str:
    return get_user_lang(user_id) or "ar"

# إظهار زر "لوحة تحكم الأمان" داخل شاشة المستخدم؟ افتراضيًا: مخفي
SHOW_INLINE_ADMIN = False

# ========= ملف الحالة =========
DATA_FILE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "security_status.json"))

DEFAULT_GAMES = {
    "8bp":  {"name": {"ar": "8Ball Pool", "en": "8Ball Pool"}, "status": "safe", "note": ""},
    "car":  {"name": {"ar": "Carrom Pool", "en": "Carrom Pool"}, "status": "safe", "note": ""},
}
DEFAULT_DATA = {
    "global": {"status": "safe", "note": "", "updated_by": None, "updated_at": None},
    "games": DEFAULT_GAMES
}

def _ensure_file():
    if not os.path.exists(DATA_FILE):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        _save(DEFAULT_DATA)

def _load() -> dict:
    try:
        _ensure_file()
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "games" not in data:
            data["games"] = DEFAULT_GAMES
        if "global" not in data:
            data["global"] = DEFAULT_DATA["global"]
        return data
    except Exception as e:
        logging.error(f"[security_status] load error: {e}")
        return DEFAULT_DATA.copy()

def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _utcnow_iso_z() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def _set_global(status: str, note: str | None, by: int):
    data = _load()
    data["global"]["status"] = status
    if note is not None:
        data["global"]["note"] = note
    data["global"]["updated_by"] = by
    data["global"]["updated_at"] = _utcnow_iso_z()
    _save(data)
    return data

def _set_game(code: str, status: str, note: str | None, by: int):
    data = _load()
    if code not in data["games"]:
        data["games"][code] = {"name": {"ar": code, "en": code}, "status": "safe", "note": ""}
    data["games"][code]["status"] = status
    if note is not None:
        data["games"][code]["note"] = note
    data["global"]["updated_by"] = by
    data["global"]["updated_at"] = _utcnow_iso_z()
    _save(data)
    return data

# === أداة تنسيق الوقت ===
def _baghdad_tz():
    return ZoneInfo("Asia/Baghdad") if ZoneInfo else datetime.timezone(datetime.timedelta(hours=3))

def _format_updated_at(dt_iso: str | None) -> str:
    """
    يعرض آخر تحديث بصيغة: 12-08-2025 14:05 UTC
    نعتمد دائمًا على UTC لتجنب مشاكل المناطق الزمنية.
    """
    if not dt_iso:
        return "-"
    try:
        s = dt_iso.strip()
        if s.endswith("Z"):
            s = s[:-1]
        dt_utc = datetime.datetime.fromisoformat(s)
        # تأكد أنها UTC
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=datetime.timezone.utc)
        else:
            dt_utc = dt_utc.astimezone(datetime.timezone.utc)
        return dt_utc.strftime("%d-%m-%Y %H:%M") + " UTC"
    except Exception:
        return dt_iso or "-"

def _now_ping_str() -> str:
    # وقت لحظي بصيغة UTC: 17:40:12 12-08-2025 UTC
    return datetime.datetime.now(tz=datetime.timezone.utc).strftime("%H:%M:%S %d-%m-%Y") + " UTC"

# ========= خرائط الحالات =========
STATUS_ORDER = ["safe", "warn", "down"]
STATUS_ICON = {
    "safe": "✅",
    "warn": "⚠️",
    "down": "❌",
}

def status_human(lang: str, st: str) -> str:
    key = {
        "safe": "sec.status.safe",
        "warn": "sec.status.warn",
        "down": "sec.status.down",
    }[st]
    return STATUS_ICON.get(st, "") + " " + t(lang, key)

# ========= واجهة المستخدم =========
def _kb_main(lang: str, as_admin: bool, *, src: str) -> InlineKeyboardBuilder:
    """
    src ∈ {'main','vip'}
    - main → زر الرجوع back_to_menu
    - vip  → زر الرجوع vip:open_tools
    كما نمرّر src في جميع أزرار التنقّل حتى يُحافظ عليها أثناء التبديل.
    """
    kb = InlineKeyboardBuilder()
    data = _load()
    games = data.get("games", {})

    # قائمة الألعاب
    for code, g in games.items():
        name = g.get("name", {}).get(lang, g.get("name", {}).get("en", code))
        icon = STATUS_ICON.get(g.get("status", "safe"), "")
        kb.button(text=f"{icon} {name}", callback_data=f"sec:game:{code}:{src}")
    kb.adjust(1)

    # زر تحديث الحالة
    kb.button(text="🔄 " + t(lang, "sec.btn_refresh"), callback_data=f"sec:refresh:{src}")
    kb.adjust(1)

    # زر لوحة التحكم (للأدمن فقط إذا مُفعّل)
    if as_admin and SHOW_INLINE_ADMIN:
        kb.button(text=t(lang, "sec.btn_admin_panel"), callback_data="sec:admin")
        kb.adjust(1)

    # رجوع حسب المصدر
    back_cb = "vip:open_tools" if src == "vip" else "back_to_menu"
    kb.button(text=t(lang, "sec.btn_back"), callback_data=back_cb)
    kb.adjust(1)
    return kb

def _kb_admin(lang: str) -> InlineKeyboardBuilder:
    data = _load()
    kb = InlineKeyboardBuilder()

    MARK_ON, MARK_OFF = "●", "○"

    # زر تحديث لوحة التحكم
    kb.button(text="🔄 " + t(lang, "sec.btn_refresh"), callback_data="sec:adm_refresh")
    kb.adjust(1)

    # === الحالة العامة ===
    g_status = data.get("global", {}).get("status", "safe")
    kb.button(
        text=f"{t(lang, 'sec.admin.global_now')}: {status_human(lang, g_status)}",
        callback_data="sec:nop",
    )
    kb.adjust(1)

    # صف اختيار الحالة العامة
    for st, emoji in (("safe", "✅"), ("warn", "⚠️"), ("down", "❌")):
        mark = MARK_ON if g_status == st else MARK_OFF
        kb.button(text=f"{mark} {emoji}", callback_data=f"sec:adm:glob:{st}")
    kb.adjust(3)

    # فاصل
    kb.button(text="— " + t(lang, "sec.admin.games") + " —", callback_data="sec:nop")
    kb.adjust(1)

    # === الألعاب ===
    games = data.get("games", {})
    for code, g in games.items():
        name = g.get("name", {}).get(lang, g.get("name", {}).get("en", code))
        cur = g.get("status", "safe")
        kb.button(text=f"🎮 {name} {STATUS_ICON.get(cur,'')}", callback_data="sec:nop")
        kb.adjust(1)
        for st, emoji in (("safe", "✅"), ("warn", "⚠️"), ("down", "❌")):
            mark = MARK_ON if cur == st else MARK_OFF
            kb.button(text=f"{mark} {emoji}", callback_data=f"sec:adm:{code}:{st}")
        kb.adjust(3)

    # رجوع إلى القائمة (عامّة)
    kb.button(text=t(lang, "sec.btn_back_list"), callback_data="sec:back_list:main")
    kb.adjust(1)
    return kb

def _main_text(lang: str, *, ping_now: bool = False) -> str:
    d = _load()
    g = d.get("global", {})
    st = g.get("status", "safe")

    # تفعيل الملاحظة حتى لو فارغة
    note = g.get("note")
    if not note or str(note).strip() == "":
        note = t(lang, "sec.no_note")  # نص افتراضي حسب اللغة

    updated_at = _format_updated_at(g.get("updated_at"))
    ping_line = f"\n⏱ {t(lang, 'sec.ping_now')}: <code>{_now_ping_str()}</code>" if ping_now else ""

    return (
        f"🛡 <b>{t(lang, 'sec.title')}</b>\n"
        f"{t(lang, 'sec.global_status')}: {status_human(lang, st)}\n"
        f"{t(lang, 'sec.note')}: <i>{note}</i>\n"
        f"{t(lang, 'sec.updated')}: <code>{updated_at}</code>{ping_line}\n\n"
        f"{t(lang, 'sec.choose_game')}"
    )

def _game_text(lang: str, code: str) -> str:
    d = _load()
    g = d.get("games", {}).get(code)
    if not g:
        return t(lang, "sec.game_not_found")
    name = g.get("name", {}).get(lang, g.get("name", {}).get("en", code))
    st = g.get("status", "safe")

    # تفعيل الملاحظة حتى لو فارغة
    note = g.get("note")
    if not note or str(note).strip() == "":
        note = t(lang, "sec.no_note")

    return (
        f"{STATUS_ICON.get(st,'')} <b>{name}</b>\n"
        f"{status_human(lang, st)}\n"
        f"{t(lang, 'sec.note')}: <i>{note}</i>"
    )

# ====== نقاط الدخول ======

# فتح من القائمة الرئيسية أو من VIP
@router.callback_query(F.data.in_({"security_status", "security_status:vip"}))
async def security_menu(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    src = "vip" if cb.data == "security_status:vip" else "main"
    try:
        await cb.message.edit_text(
            _main_text(lang),
            reply_markup=_kb_main(lang, is_admin(cb.from_user.id), src=src).as_markup()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await cb.answer()

# تحديث الشاشة الرئيسية (يحافظ على مصدر الفتح)
@router.callback_query(F.data.regexp(r"^sec:refresh:(vip|main)$"))
async def security_refresh(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    _, _, src = cb.data.split(":")
    try:
        await cb.message.edit_text(
            _main_text(lang, ping_now=True),
            reply_markup=_kb_main(lang, is_admin(cb.from_user.id), src=src).as_markup()
        )
        await cb.answer(t(lang, "sec.refreshed"))
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            await cb.answer(t(lang, "sec.no_changes"))
        else:
            raise

# عرض لعبة معيّنة (مع رجوع إلى نفس المصدر)
@router.callback_query(F.data.regexp(r"^sec:game:([^:]+):(vip|main)$"))
async def security_game(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    _, _, code, src = cb.data.split(":")
    kb = InlineKeyboardBuilder()
    kb.button(text=f"{t(lang, 'sec.btn_back_list')}", callback_data=f"sec:back_list:{src}")
    kb.adjust(1)
    try:
        await cb.message.edit_text(_game_text(lang, code), reply_markup=kb.as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await cb.answer()

# رجوع إلى القائمة (يحافظ على المصدر)
@router.callback_query(F.data.regexp(r"^sec:back_list:(vip|main)$"))
async def security_back_list(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    _, _, src = cb.data.split(":")
    try:
        await cb.message.edit_text(
            _main_text(lang),
            reply_markup=_kb_main(lang, is_admin(cb.from_user.id), src=src).as_markup()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await cb.answer()

# ====== لوحة تحكم الأدمن (إنلاين) ======
@router.callback_query(F.data == "sec:admin")
async def security_admin(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "sec.admin.only_admin"), show_alert=True)
    try:
        await cb.message.edit_text("🛠 " + t(lang, "sec.admin.title"), reply_markup=_kb_admin(lang).as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await cb.answer()

# تحديث لوحة التحكم
@router.callback_query(F.data == "sec:adm_refresh")
async def security_admin_refresh(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "sec.admin.only_admin"), show_alert=True)
    try:
        await cb.message.edit_text("🛠 " + t(lang, "sec.admin.title"), reply_markup=_kb_admin(lang).as_markup())
        await cb.answer(t(lang, "sec.refreshed"))
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            await cb.answer(t(lang, "sec.no_changes"))
        else:
            raise

@router.callback_query(F.data.startswith("sec:adm:"))
async def security_admin_action(cb: CallbackQuery):
    lang = L(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        return await cb.answer(t(lang, "sec.admin.only_admin"), show_alert=True)

    parts = cb.data.split(":")  # sec, adm, <scope or code>, <status>
    if len(parts) != 4:
        return await cb.answer()

    scope_or_code = parts[2]
    status = parts[3]
    if scope_or_code == "glob":
        _set_global(status, None, cb.from_user.id)
    else:
        _set_game(scope_or_code, status, None, cb.from_user.id)

    try:
        await cb.message.edit_text("🛠 " + t(lang, "sec.admin.updated_ok"), reply_markup=_kb_admin(lang).as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await cb.answer()

@router.callback_query(F.data == "sec:nop")
async def security_nop(cb: CallbackQuery):
    await cb.answer()

# ====== أوامر أدمن (نصية) ======
# /sec_set safe|warn|down [note...]
@router.message(Command("sec_set"))
async def cmd_sec_set(m: Message):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(t(lang, "sec.admin.only_admin"))
    toks = (m.text or "").split(maxsplit=2)
    if len(toks) < 2 or toks[1] not in STATUS_ORDER:
        return await m.reply(t(lang, "sec.admin.usage_set"))
    status = toks[1]
    note = toks[2] if len(toks) > 2 else None
    _set_global(status, note, m.from_user.id)
    await m.reply(t(lang, "sec.admin.updated_ok"))

# /sec_game <code> safe|warn|down [note...]
@router.message(Command("sec_game"))
async def cmd_sec_game(m: Message):
    lang = L(m.from_user.id)
    if not is_admin(m.from_user.id):
        return await m.reply(t(lang, "sec.admin.only_admin"))
    toks = (m.text or "").split(maxsplit=3)
    if len(toks) < 3 or toks[2] not in STATUS_ORDER:
        return await m.reply(t(lang, "sec.admin.usage_game"))
    code = toks[1]
    status = toks[2]
    note = toks[3] if len(toks) > 3 else None
    _set_game(code, status, note, m.from_user.id)
    await m.reply(t(lang, "sec.admin.updated_ok"))
