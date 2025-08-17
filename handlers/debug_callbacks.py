import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import StateFilter

router = Router(name="debug_callbacks")

# ✅ اطبع أي كولباك غير ممسوك — لكن فقط عندما لا توجد حالة FSM
@router.callback_query(StateFilter(None))
async def _dbg_any_callback(cb: CallbackQuery):
    data = cb.data if hasattr(cb, "data") else None
    logging.warning(f"[DBG] Unhandled callback: {data!r} from user {cb.from_user.id}")
    await cb.answer()

# ✅ اطبع أي رسالة غير ممسوكة — لكن فقط عندما لا توجد حالة FSM
@router.message(StateFilter(None))
async def _dbg_any_message(msg: Message):
    ct = getattr(msg, "content_type", "?")
    txt = getattr(msg, "text", None)
    logging.warning(f"[DBG] Unhandled message: type={ct} text={txt!r} user={msg.from_user.id if msg.from_user else '-'}")
