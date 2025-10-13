from __future__ import annotations

# handlers/history_cleanup.py


from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from lang import t, get_user_lang
from .rewards_gate import require_membership
from utils.rewards_store import ensure_user
from utils.rewards_store import purge_user_history

# كابتشا بشرية (مع fallback آمن)
try:
    from .human_check import require_human, ensure_human_then  # type: ignore
except Exception:
    async def require_human(msg_or_cb, level: str = "normal") -> bool:
        return True
    async def ensure_human_then(msg_or_cb, level: str, resume):
        if await require_human(msg_or_cb, level=level):
            await resume(msg_or_cb)
            return True
        return False

router = Router(name="history_cleanup")

def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _tt(lang: str, key: str, fb: str) -> str:
    try:
        val = t(lang, key)
        if isinstance(val, str) and val.strip() and val != key:
            return val
    except Exception:
        pass
    return fb

# ------------- Keyboards -------------
def _kb_clean_menu(lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_tt(lang, "hist.clean.today", "🗑️ مسح اليوم"),
                             callback_data="rprof:history:clean:pick:today"),
        InlineKeyboardButton(text=_tt(lang, "hist.clean.7d", "🗑️ آخر 7 أيام"),
                             callback_data="rprof:history:clean:pick:7d"),
    )
    kb.row(
        InlineKeyboardButton(text=_tt(lang, "hist.clean.30d", "🗑️ آخر 30 يومًا"),
                             callback_data="rprof:history:clean:pick:30d"),
        InlineKeyboardButton(text=_tt(lang, "hist.clean.all", "🗑️ مسح الكل"),
                             callback_data="rprof:history:clean:pick:all"),
    )
    kb.row(InlineKeyboardButton(text=_tt(lang, "hist.clean.back", "⬅️ رجوع"), callback_data="rprof:history:p:1"))
    return kb

def _kb_confirm(lang: str, scope: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_tt(lang, "hist.clean.confirm", "✅ تأكيد المسح"),
                             callback_data=f"rprof:history:clean:do:{scope}"),
        InlineKeyboardButton(text=_tt(lang, "hist.clean.cancel", "✖️ إلغاء"),
                             callback_data="rprof:history:clean"),
    )
    return kb

# ------------- Open Clean Menu -------------
@router.callback_query(F.data == "rprof:history:clean")
async def open_clean_menu(cb: CallbackQuery):
    uid = cb.from_user.id
    lang = _L(uid)

    if await require_membership(cb) is False:
        return

    async def _show(_):
        text = _tt(lang, "hist.clean.title", "🧹 تنظيف السجل") + "\n" + \
               _tt(lang, "hist.clean.choose", "اختر ما تريد حذفه:")
        try:
            await cb.message.edit_text(text, reply_markup=_kb_clean_menu(lang).as_markup())
        except TelegramBadRequest:
            await cb.message.answer(text, reply_markup=_kb_clean_menu(lang).as_markup())

    await ensure_human_then(cb, level="normal", resume=_show)

# ------------- Pick scope -> ask confirm -------------
@router.callback_query(F.data.startswith("rprof:history:clean:pick:"))
async def ask_confirm(cb: CallbackQuery):
    uid = cb.from_user.id
    lang = _L(uid)
    scope = cb.data.split(":")[-1]  # today / 7d / 30d / all

    name_map = {
        "today": _tt(lang, "hist.clean.today", "مسح اليوم"),
        "7d":    _tt(lang, "hist.clean.7d", "آخر 7 أيام"),
        "30d":   _tt(lang, "hist.clean.30d", "آخر 30 يومًا"),
        "all":   _tt(lang, "hist.clean.all", "مسح الكل"),
    }
    text = _tt(lang, "hist.clean.confirm_q", "هل أنت متأكد من {what}؟").format(what=name_map.get(scope, scope))
    try:
        await cb.message.edit_text(text, reply_markup=_kb_confirm(lang, scope).as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=_kb_confirm(lang, scope).as_markup())

# ------------- Do purge -------------
@router.callback_query(F.data.startswith("rprof:history:clean:do:"))
async def do_purge(cb: CallbackQuery):
    uid = cb.from_user.id
    lang = _L(uid)
    scope = cb.data.split(":")[-1]

    if await require_membership(cb) is False:
        return

    async def _work(_):
        ensure_user(uid)  # تأكد من وجود الحساب
        removed = purge_user_history(uid, scope=scope)  # يحذف بدون المساس بالرصيد

        # أعد فتح صفحة السجل إن أمكن، وإلا ارجع للملف الشخصي
        msg = _tt(lang, "hist.clean.done", "تم حذف {n} عملية من السجل.").format(n=removed)
        await cb.answer(msg, show_alert=True)

        # حاول الرجوع إلى السجل مباشرةً (صفحة 1)
        try:
            # إذا كانت شاشة السجل تعرف هذا الكولباك
            await cb.message.edit_text(
                _tt(lang, "hist.clean.backtext", "تم التنظيف."),
                reply_markup=InlineKeyboardBuilder()
                    .row(InlineKeyboardButton(text=_tt(lang, "hist.clean.to_history", "📜 عرض السجل"),
                                              callback_data="rprof:history:p:1"))
                    .row(InlineKeyboardButton(text=_tt(lang, "hist.clean.to_profile", "👤 الملف الشخصي"),
                                              callback_data="rprof:back"))
                    .as_markup()
            )
        except Exception:
            # كخطة بديلة افتح بروفايل الجوائز
            try:
                from . import rewards_profile_pro as _pro
                if hasattr(_pro, "open_profile"):
                    await _pro.open_profile(cb, edit=True)
                else:
                    await cb.message.answer("✅ " + msg)
            except Exception:
                await cb.message.answer("✅ " + msg)

    await ensure_human_then(cb, level="high", resume=_work)
