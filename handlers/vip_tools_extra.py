# handlers/vip_tools_extra.py
from __future__ import annotations

import os, json, datetime as dt
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from lang import t, get_user_lang

try:
    from utils.vip_store import is_vip
except Exception:
    def is_vip(_): return False

router = Router(name="vip_tools_extra")

# ───────────── إعدادات وتخزين بسيط للطلبات ─────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)
REQ_FILE = os.path.join(DATA_DIR, "vip_requests.json")

def _load_reqs() -> list[dict]:
    try:
        with open(REQ_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception:
        return []

def _save_reqs(lst: list[dict]):
    tmp = f"{REQ_FILE}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lst, f, ensure_ascii=False, indent=2)
    os.replace(tmp, REQ_FILE)

def _append_req(item: dict):
    lst = _load_reqs()
    lst.append(item)
    _save_reqs(lst)

# ========= أزرار إضافية تُدمج في القائمة الرئيسية =========
def vip_extra_buttons(lang: str):
    """
    تُعاد كمصفوفة صفوف: [[Button, Button], [Button], ...]
    تُستدعى من handlers/vip_features._kb_vip_tools()
    """
    return [
        # إدارة الاشتراك
        [InlineKeyboardButton(text="🗂 " + t(lang, "vip.manage_ids"),
                              callback_data="viptool:manage_ids")],
        [InlineKeyboardButton(text="📤 " + t(lang, "vip.tools.transfer"),
                              callback_data="viptool:transfer")],
        [InlineKeyboardButton(text="🔁 " + t(lang, "vip.renew"),
                              callback_data="viptool:renew")],
        # الأمان والدعم
        [
            # يفتح شاشة الأمان الحقيقية (handlers/security_status.py)
            InlineKeyboardButton(text="🛡️ " + t(lang, "vip.security"),
                                 callback_data="security_status"),
            # يبدأ تدفّق الإبلاغ الموجود في handlers/report_seller.py
            InlineKeyboardButton(text="🚩 " + t(lang, "vip.tools.report_seller"),
                                 callback_data="report_seller:start"),
        ],
    ]

# ───────────── الأدوات: إدارة المعرّفات كطلبات ─────────────
class ManageIdForm(StatesGroup):
    choose = State()
    app_add = State()
    app_remove = State()

@router.callback_query(F.data == "viptool:manage_ids")
async def manage_ids_menu(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"
    if not is_vip(cb.from_user.id):
        return await cb.answer(t(lang, "vip.bad.not_vip"), show_alert=True)

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="➕ " + t(lang, "vip.ids.add"), callback_data="viptool:ids:add"),
        InlineKeyboardButton(text="🗑 " + t(lang, "vip.ids.remove"), callback_data="viptool:ids:remove"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ " + t(lang, "vip.back"), callback_data="vip:open_tools"))
    await cb.message.edit_text("🗂 " + t(lang, "vip.ids.title"), reply_markup=kb.as_markup())
    await state.set_state(ManageIdForm.choose)
    await cb.answer()

@router.callback_query(F.data == "viptool:ids:add")
async def ids_add_start(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.answer("➕ " + t(lang, "vip.ids.ask_add"))
    await state.set_state(ManageIdForm.app_add)
    await cb.answer()

@router.message(ManageIdForm.app_add)
async def ids_add_finish(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    app_id = msg.text.strip()
    if not app_id or not app_id.replace("-", "").replace("_", "").replace(".", "").isalnum():
        return await msg.reply(t(lang, "vip.ids.bad_id"))
    _append_req({
        "type": "add_id",
        "user_id": msg.from_user.id,
        "app_id": app_id,
        "when": dt.datetime.utcnow().isoformat() + "Z",
    })
    await msg.reply("✅ " + t(lang, "vip.ids.added_req"))
    await state.clear()

@router.callback_query(F.data == "viptool:ids:remove")
async def ids_remove_start(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.answer("🗑 " + t(lang, "vip.ids.ask_remove"))
    await state.set_state(ManageIdForm.app_remove)
    await cb.answer()

@router.message(ManageIdForm.app_remove)
async def ids_remove_finish(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    app_id = msg.text.strip()
    if not app_id or not app_id.replace("-", "").replace("_", "").replace(".", "").isalnum():
        return await msg.reply(t(lang, "vip.ids.bad_id"))
    _append_req({
        "type": "remove_id",
        "user_id": msg.from_user.id,
        "app_id": app_id,
        "when": dt.datetime.utcnow().isoformat() + "Z",
    })
    await msg.reply("✅ " + t(lang, "vip.ids.removed_req"))
    await state.clear()

# ───────────── الأدوات: نقل الاشتراك ─────────────
class TransferForm(StatesGroup):
    app = State()
    target = State()
    note = State()

@router.callback_query(F.data == "viptool:transfer")
async def transfer_start(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id) or "en"
    if not is_vip(cb.from_user.id):
        return await cb.answer(t(lang, "vip.bad.not_vip"), show_alert=True)
    await cb.message.answer("📤 " + t(lang, "vip.transfer.ask_app"))
    await state.set_state(TransferForm.app)
    await cb.answer()

@router.message(TransferForm.app)
async def transfer_got_app(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    app_id = msg.text.strip()
    if not app_id or not app_id.replace("-", "").replace("_", "").replace(".", "").isalnum():
        return await msg.reply(t(lang, "vip.ids.bad_id"))
    await state.update_data(app_id=app_id)
    await msg.reply(t(lang, "vip.transfer.ask_target"))
    await state.set_state(TransferForm.target)

@router.message(TransferForm.target)
async def transfer_got_target(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    target = msg.text.strip()
    if not target.isdigit():
        return await msg.reply(t(lang, "vip.transfer.bad_target"))
    await state.update_data(target=int(target))
    await msg.reply(t(lang, "vip.transfer.ask_note"))
    await state.set_state(TransferForm.note)

@router.message(TransferForm.note)
async def transfer_finish(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id) or "en"
    note = (msg.text or "").strip()
    data = await state.get_data()
    item = {
        "type": "transfer",
        "user_id": msg.from_user.id,
        "app_id": data["app_id"],
        "target_user": data["target"],
        "note": note,
        "when": dt.datetime.utcnow().isoformat() + "Z",
    }
    _append_req(item)
    await state.clear()

    # إخطار الأدمن
    try:
        from aiogram import Bot
        bot: Bot = msg.bot
        admins = []
        env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
        for p in env.split(","):
            p = p.strip()
            if p.isdigit():
                admins.append(int(p))
        text = (f"🔁 VIP Transfer Request\n"
                f"• From: <code>{msg.from_user.id}</code>\n"
                f"• APP: <code>{item['app_id']}</code>\n"
                f"• To: <code>{item['target_user']}</code>\n"
                f"• Note: {note or '-'}")
        for uid in admins:
            try: await bot.send_message(uid, text)
            except Exception: pass
    except Exception:
        pass

    await msg.reply("✅ " + t(lang, "vip.transfer.submitted"))

# ───────────── الأدوات: تجديد/ترقية ─────────────
@router.callback_query(F.data == "viptool:renew")
async def vip_renew(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    if not is_vip(cb.from_user.id):
        return await cb.answer(t(lang, "vip.bad.not_vip"), show_alert=True)
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✅ " + t(lang, "btn_verified_resellers_short"),
                                callback_data="viptool:open_resellers"))
    await cb.message.answer("🔁 " + t(lang, "vip_renew_text"), reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data == "viptool:open_resellers")
async def open_resellers(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.answer("✅ " + t(lang, "verified_resellers_intro"))
    await cb.answer()

# ───────────── توافق للخلف لزر الأمان القديم ─────────────
@router.callback_query(F.data == "viptool:security")
async def vip_security_compat(cb: CallbackQuery):
    try:
        from handlers.security_status import security_menu
        await security_menu(cb)
    except Exception:
        lang = get_user_lang(cb.from_user.id) or "en"
        await cb.message.answer("🛡️ " + t(lang, "security_select_game"))
    await cb.answer()
