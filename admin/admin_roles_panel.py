from __future__ import annotations

# admin/admin_roles_panel.py


import json
from pathlib import Path
from typing import Dict, List

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from lang import t as _t, get_user_lang
from utils.paths import BASE
from utils.admins import is_admin as _is_admin, ADMIN_IDS as _DYN_DEFAULT_IDS

router = Router(name="admin_roles_panel")

# ---------- التخزين ----------
ROLES_FILE: Path = BASE / "admin_roles.json"
_DEFAULT_MAP = {"default": [], "reports": [], "livechat": [], "sales": []}


def _load_roles() -> Dict[str, List[int]]:
    try:
        if ROLES_FILE.exists():
            data = json.loads(ROLES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in _DEFAULT_MAP:
                    data.setdefault(k, [])
                return {k: [int(x) for x in (v or [])] for k, v in data.items()}
    except Exception:
        pass
    # deep copy
    return json.loads(json.dumps(_DEFAULT_MAP))


def _save_roles(m: Dict[str, List[int]]) -> None:
    for k in _DEFAULT_MAP:
        m.setdefault(k, [])
    ROLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    ROLES_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")


def _roles_list() -> List[str]:
    return list(_DEFAULT_MAP.keys())


# ---------- i18n صغيرة ----------
def _tt(lang: str, key: str, ar: str, en: str | None = None) -> str:
    """
    ترجمة مبسطة:
    - يحاول جلب النص من ملف اللغات (lang.t).
    - إن لم يجد، يستخدم 'ar' كبديل.
    - إذا تم تمرير وسيط رابع 'en'، يختار بين (ar/en) حسب اللغة.
    """
    try:
        v = _t(lang, key)
        if isinstance(v, str) and v.strip() and v != key:
            return v
    except Exception:
        pass

    # إذا أُعطي بديلان، اختر حسب اللغة
    if en is not None:
        return ar if str(lang).startswith("ar") else en
    # وإلا اعتبر 'ar' هو البديل الوحيد
    return ar


def _role_label(role: str, lang: str) -> str:
    role = (role or "").lower()
    if str(lang).startswith("ar"):
        return {
            "default": "الافتراضي",
            "reports": "التقارير",
            "livechat": "الدردشة",
            "sales": "المبيعات",
        }.get(role, role)
    return {
        "default": "default",
        "reports": "reports",
        "livechat": "livechat",
        "sales": "sales",
    }.get(role, role)


def _fmt_ids(ids: List[int], lang: str) -> str:
    if ids:
        return ", ".join(map(str, ids))
    empty = _tt(lang, "admacc.empty", "فارغ" if str(lang).startswith("ar") else "empty")
    return f"({empty})"


def _parse_ids(tokens: List[str]) -> List[int]:
    out: List[int] = []
    joined = " ".join(tokens).replace(",", " ")
    for tok in joined.split():
        tok = tok.strip().lstrip("+")
        if tok.startswith("@"):
            continue
        try:
            out.append(int(tok))
        except Exception:
            continue
    # إزالة التكرار مع الحفاظ على الترتيب
    seen = set()
    dedup: List[int] = []
    for v in out:
        if v not in seen:
            seen.add(v)
            dedup.append(v)
    return dedup


# ---------- نص اللوحة ----------
def _panel_text(lang: str) -> str:
    m = _load_roles()
    title = _tt(lang, "admacc.title", "إدارة الأدمن 👥")
    tip = _tt(
        lang,
        "admacc.tip",
        "استخدم الأزرار لإضافة/إزالة/تعيين IDs للأدوار.\n"
        "يمكن استخدام IDs سالبة للقنوات/المجموعات.",
    )
    map_title = _tt(
        lang,
        "admacc.map_title",
        "مخطط الأدوار:" if str(lang).startswith("ar") else "Admin roles mapping:",
    )
    lines = [f"<b>{title}</b>", tip, "", map_title]
    for role in _roles_list():
        lines.append(f"– {_role_label(role, lang)}: {_fmt_ids(m.get(role, []), lang)}")
    return "\n".join(lines)


# ---------- الكيبورد ----------
def _kb_main(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_tt(lang, "admacc.btn.view", "عرض الأدوار 📋", "View 📋"), callback_data="admacc:refresh")],
        [
            InlineKeyboardButton(text=_role_label("default", lang),  callback_data="admacc:role:default"),
            InlineKeyboardButton(text=_role_label("reports", lang),  callback_data="admacc:role:reports"),
        ],
        [
            InlineKeyboardButton(text=_role_label("livechat", lang), callback_data="admacc:role:livechat"),
            InlineKeyboardButton(text=_role_label("sales", lang),    callback_data="admacc:role:sales"),
        ],
        [InlineKeyboardButton(text=_tt(lang, "admacc.btn.import", "استيراد من قائمة الأدمن الحالية ⤵️", "Import current admins ⤵️"),
                              callback_data="admacc:import")],
        [InlineKeyboardButton(text=_tt(lang, "admacc.btn.back", "رجوع ⬅️", "Back ⬅️"),
                              callback_data="ah:menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_role(role: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_tt(lang, "admacc.btn.add", "إضافة ➕", "Add ➕"),
                                 callback_data=f"admacc:add:{role}"),
            InlineKeyboardButton(text=_tt(lang, "admacc.btn.remove", "إزالة ➖", "Remove ➖"),
                                 callback_data=f"admacc:rem:{role}"),
        ],
        [
            InlineKeyboardButton(text=_tt(lang, "admacc.btn.set", "تعيين للدور 🎯", "Set role 🎯"),
                                 callback_data=f"admacc:set:{role}"),
            InlineKeyboardButton(text=_tt(lang, "admacc.btn.clear", "مسح للدور 🧹", "Clear 🧹"),
                                 callback_data=f"admacc:clear:{role}"),
        ],
        [InlineKeyboardButton(text=_tt(lang, "admacc.btn.back", "⬅️ رجوع", "⬅️ Back"), callback_data="admacc:open")]
    ])


def _kb_confirm_clear(role: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_tt(lang, "admacc.btn.yes", "نعم، مسح", "Yes, clear"),
                                 callback_data=f"admacc:clrgo:{role}"),
            InlineKeyboardButton(text=_tt(lang, "admacc.btn.cancel", "إلغاء", "Cancel"),
                                 callback_data=f"admacc:role:{role}"),
        ]
    ])


# ---------- FSM لاستلام IDs ----------
class RoleEdit(StatesGroup):
    wait_ids = State()  # data: {"role": str, "mode": "add"|"rem"|"set"}


# ---------- الدخول للوحة ----------
@router.message(Command("admins_panel"))
async def cmd_open(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    await state.clear()
    lang = get_user_lang(msg.from_user.id) or "ar"
    await msg.answer(_panel_text(lang), reply_markup=_kb_main(lang),
                     parse_mode=ParseMode.HTML, disable_web_page_preview=True)


# يمكن فتحها من الهَب الإداري
@router.callback_query(F.data == "admacc:open")
async def cb_open(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    await state.clear()
    lang = get_user_lang(cb.from_user.id) or "ar"
    try:
        await cb.message.edit_text(_panel_text(lang), reply_markup=_kb_main(lang),
                                   parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        await cb.message.answer(_panel_text(lang), reply_markup=_kb_main(lang),
                                parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await cb.answer()


@router.callback_query(F.data == "admacc:refresh")
async def cb_refresh(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "ar"
    try:
        await cb.message.edit_text(_panel_text(lang), reply_markup=_kb_main(lang),
                                   parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        pass
    await cb.answer("OK")


# ---------- قائمة دور معيّن ----------
@router.callback_query(F.data.startswith("admacc:role:"))
async def cb_role(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    await state.clear()
    role = cb.data.split(":")[-1]
    lang = get_user_lang(cb.from_user.id) or "ar"
    m = _load_roles()
    ids = _fmt_ids(m.get(role, []), lang)
    text = _tt(lang, "admacc.role.view",
               "🎛️ <b>{role}</b>\nالمعيّنون: {ids}",
               ).format(role=_role_label(role, lang), ids=ids)
    try:
        await cb.message.edit_text(text, reply_markup=_kb_role(role, lang), parse_mode=ParseMode.HTML)
    except Exception:
        await cb.message.answer(text, reply_markup=_kb_role(role, lang), parse_mode=ParseMode.HTML)
    await cb.answer()


# ---------- مسح الدور (تأكيد) ----------
@router.callback_query(F.data.startswith("admacc:clear:"))
async def cb_clear_ask(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    role = cb.data.split(":")[-1]
    lang = get_user_lang(cb.from_user.id) or "ar"
    txt = _tt(lang, "admacc.clear.ask", "هل تريد مسح كل IDs من هذا الدور؟")
    await cb.message.edit_text(txt, reply_markup=_kb_confirm_clear(role, lang))
    await cb.answer()


@router.callback_query(F.data.startswith("admacc:clrgo:"))
async def cb_clear_do(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    role = cb.data.split(":")[-1]
    lang = get_user_lang(cb.from_user.id) or "ar"
    m = _load_roles()
    n = len(m.get(role, []))
    m[role] = []
    _save_roles(m)
    await cb.answer("Cleared")
    await cb.message.edit_text(
        _tt(lang, "admacc.done.clear", "تم مسح {n} عنصر.").format(n=n),
        reply_markup=_kb_role(role, lang)
    )


# ---------- بدء إدخال IDs (إضافة/إزالة/تعيين) ----------
@router.callback_query(F.data.regexp(r"^admacc:(add|rem|set):"))
async def cb_start_edit(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    mode, role = cb.data.split(":")[1:3]
    lang = get_user_lang(cb.from_user.id) or "ar"
    await state.set_state(RoleEdit.wait_ids)
    await state.update_data(role=role, mode=mode)
    if lang.startswith("ar"):
        hint = "أرسل IDs مفصولة بمسافات أو فواصل.\nمثال: 123 456 789 أو 123,456,789\n(/cancel للإلغاء)"
    else:
        hint = "Send IDs separated by spaces or commas.\nExample: 123 456 789 or 123,456,789\n(/cancel to cancel)"
    await cb.message.edit_text(hint, reply_markup=_kb_role(role, lang))
    await cb.answer()


@router.message(RoleEdit.wait_ids)
async def msg_receive_ids(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    data = await state.get_data()
    role = str(data.get("role"))
    mode = str(data.get("mode"))
    lang = get_user_lang(msg.from_user.id) or "ar"

    ids = _parse_ids([msg.text or ""])
    if not ids:
        return await msg.reply(_tt(lang, "admacc.no_ids", "لم يتم العثور على IDs."))

    m = _load_roles()
    before_set = set(m.get(role, []))

    if mode == "add":
        after = sorted(before_set | set(ids))
        m[role] = after
        _save_roles(m)
        diff = len(after) - len(before_set)
        await msg.reply(_tt(lang, "admacc.done.add", "تمت الإضافة: {n}").format(n=diff))

    elif mode == "rem":
        after = [x for x in before_set if x not in set(ids)]
        m[role] = sorted(after)
        _save_roles(m)
        diff = len(before_set) - len(after)
        await msg.reply(_tt(lang, "admacc.done.remove", "تمت الإزالة: {n}").format(n=diff))

    else:  # set
        m[role] = sorted(set(ids))
        _save_roles(m)
        await msg.reply(_tt(lang, "admacc.done.set", "تم التعيين: {n} عنصر.").format(n=len(m[role])))

    await state.clear()
    # عرض قائمة الدور مجددًا
    ids_text = _fmt_ids(m.get(role, []), lang)
    text = _tt(lang, "admacc.role.view",
               "🎛️ <b>{role}</b>\nالمعيّنون: {ids}",
               ).format(role=_role_label(role, lang), ids=ids_text)
    await msg.answer(text, reply_markup=_kb_role(role, lang), parse_mode=ParseMode.HTML)


# ---------- إلغاء أثناء الإدخال ----------
@router.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    data = await state.get_data()
    role = str(data.get("role") or "default")
    await state.clear()
    lang = get_user_lang(msg.from_user.id) or "ar"
    m = _load_roles()
    ids_text = _fmt_ids(m.get(role, []), lang)
    txt = _tt(lang, "admacc.role.view",
              "🎛️ <b>{role}</b>\nالمعيّنون: {ids}",
              ).format(role=_role_label(role, lang), ids=ids_text)
    await msg.answer(txt, reply_markup=_kb_role(role, lang), parse_mode=ParseMode.HTML)


# ---------- استيراد من قائمة الأدمن الحالية إلى default ----------
@router.callback_query(F.data == "admacc:import")
async def cb_import(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Admins only.", show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "ar"

    src = [int(x) for x in (_DYN_DEFAULT_IDS or [])]
    if not src:
        return await cb.answer(_tt(lang, "admacc.src_empty", "لا توجد قائمة أدمن حالية."), show_alert=True)

    m = _load_roles()
    cur = set(m.get("default", []))
    before = len(cur)
    for x in src:
        cur.add(int(x))
    m["default"] = sorted(cur)
    _save_roles(m)

    added = len(cur) - before
    try:
        await cb.message.edit_text(_panel_text(lang), reply_markup=_kb_main(lang),
                                   parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        pass
    await cb.answer(_tt(lang, "admacc.done.import", "تم الاستيراد، عناصر مضافة: {n}").format(n=added))
