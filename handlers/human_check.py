# handlers/human_check.py
from __future__ import annotations
from typing import Callable, Awaitable, Dict, Union
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from lang import t, get_user_lang
from utils.anti_cheat import (
    need_captcha, build_captcha, try_captcha, is_temporarily_banned
)

router = Router(name="human_check")

# ===== ترجمة سريعة =====
def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _tt(lang: str, key: str, fb: str) -> str:
    try:
        v = t(lang, key)
        if isinstance(v, str) and v.strip() and v != key:
            return v
    except Exception:
        pass
    return fb

# ===== تخزين “المتابعة بعد التحقق” =====
ResumeEvent = Union[Message, CallbackQuery]
ResumeFn = Callable[[ResumeEvent], Awaitable[None]]
_PENDING_RESUME: Dict[int, ResumeFn] = {}   # user_id -> coroutine

# ===== إرسال الكابتشا =====
async def _send_captcha(msg_or_cb: ResumeEvent):
    uid = msg_or_cb.from_user.id
    lang = _L(uid)

    if is_temporarily_banned(uid):
        txt = _tt(lang, "ac.cooldown", "محاولات كثيرة. حاول لاحقًا.")
        if isinstance(msg_or_cb, Message):
            return await msg_or_cb.answer(txt)
        return await msg_or_cb.answer(txt, show_alert=True)

    text, opts, _, token = build_captcha(uid)
    kb = InlineKeyboardBuilder()
    for i, e in enumerate(opts):
        kb.add(InlineKeyboardButton(text=e, callback_data=f"hc:try:{token}:{i}"))
    kb.adjust(3, 3)
    markup = kb.as_markup()

    if isinstance(msg_or_cb, Message):
        await msg_or_cb.answer(text, reply_markup=markup)
    else:
        await msg_or_cb.message.answer(text, reply_markup=markup)

# ===== واجهات عامة =====
async def require_human(msg_or_cb: ResumeEvent, level: str = "normal") -> bool:
    """
    تُرجع True إن كان المستخدم متحققًا الآن.
    إن لزم كابتشا: تُرسلها وترجع False (لن يتم تنفيذ الإجراء).
    """
    uid = msg_or_cb.from_user.id
    if not need_captcha(uid, level=level):
        return True
    await _send_captcha(msg_or_cb)
    return False

async def ensure_human_then(msg_or_cb: ResumeEvent, level: str, resume: ResumeFn) -> bool:
    """
    إن كان المستخدم متحققًا: ينفّذ resume فورًا ويُرجع True.
    إن لم يكن: يرسل الكابتشا ويخزّن resume ليُنفّذ تلقائيًا بعد النجاح، ثم يُرجع False.
    """
    uid = msg_or_cb.from_user.id
    if not need_captcha(uid, level=level):
        await resume(msg_or_cb)
        return True
    _PENDING_RESUME[uid] = resume
    await _send_captcha(msg_or_cb)
    return False

# ===== معالجة أزرار الكابتشا =====
@router.callback_query(F.data.startswith("hc:try:"))
async def _cb_try(cb: CallbackQuery):
    uid = cb.from_user.id
    lang = _L(uid)
    ok = False
    try:
        _, _, token, idx = cb.data.split(":")
        ok = try_captcha(uid, token, int(idx))
    except Exception:
        ok = False

    if ok:
        await cb.answer(_tt(lang, "ac.ok", "تم التحقق ✅"), show_alert=False)
        # نفّذ الإجراء المعلّق (إن وُجد)
        resume = _PENDING_RESUME.pop(uid, None)
        if resume:
            try:
                await resume(cb)
            except Exception:
                # نتجاهل أي خطأ هنا حتى لا يؤثر على تجربة الكابتشا
                pass
    else:
        await cb.answer(_tt(lang, "ac.bad", "تحقق فاشل."), show_alert=True)
