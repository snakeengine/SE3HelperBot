# handlers/rewards_hub.py
from __future__ import annotations

import time
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from lang import t, get_user_lang
from utils.rewards_store import (
    get_points, ensure_user, can_do, mark_action, daily_claim, is_blocked
)
from .rewards_gate import require_membership

router = Router(name="rewards_hub")

def _L(uid: int) -> str:
    return get_user_lang(uid) or "en"

def _hub_kb(lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=t(lang, "rewards.hub.market", "🎁 المتجر"), callback_data="rwd:hub:market"),
        InlineKeyboardButton(text=t(lang, "rewards.hub.wallet", "👛 محفظتي"), callback_data="rwd:hub:wallet"),
    )
    kb.row(InlineKeyboardButton(text=t(lang, "rewards.hub.how", "ℹ️ شرح الاستخدام"), callback_data="rwd:hub:how"))
    kb.row(InlineKeyboardButton(text=t(lang, "rewards.hub.daily", "🎯 نقاط يومية"), callback_data="rwd:hub:daily"))
    return kb

async def open_hub(msg_or_cb: Message | CallbackQuery, edit: bool = False):
    uid = msg_or_cb.from_user.id
    lang = _L(uid)
    ensure_user(uid)

    # Gate
    if await require_membership(msg_or_cb) is False:
        return

    pts = get_points(uid)
    text = t(lang, "rewards.hub.title", "🎉 أهلاً بك في الجوائز!") + "\n"
    text += t(lang, "rewards.hub.balance", "رصيدك الحالي: {points}").format(points=pts)

    kb = _hub_kb(lang).as_markup()
    if isinstance(msg_or_cb, Message):
        await msg_or_cb.answer(text, reply_markup=kb)
    else:
        if edit and msg_or_cb.message:
            await msg_or_cb.message.edit_text(text, reply_markup=kb)
        else:
            await msg_or_cb.answer(text, show_alert=True)

@router.message(Command("rewards_hub"))
async def cmd_rewards_hub(m: Message):
    await open_hub(m)

@router.callback_query(F.data == "rwd:hub")
async def cb_hub_root(cb: CallbackQuery):
    await open_hub(cb, edit=True)

@router.callback_query(F.data == "rwd:hub:how")
async def cb_how(cb: CallbackQuery):
    uid = cb.from_user.id
    lang = _L(uid)
    if await require_membership(cb) is False:
        return
    text = t(lang, "rewards.hub.how_text",
             "• اشترك بالقنوات الإلزامية.\n• اجمع نقاطك من المهام والمتجر.\n• استخدم رصيدك للشراء أو التحويل.")
    await cb.message.edit_text(text, reply_markup=_hub_kb(lang).as_markup())

@router.callback_query(F.data == "rwd:hub:daily")
async def cb_daily(cb: CallbackQuery):
    uid = cb.from_user.id
    lang = _L(uid)
    if await require_membership(cb) is False:
        return

    # Simple throttle: once per 20s
    if not can_do(uid, "daily_click", cooldown_sec=20):
        return await cb.answer(t(lang, "common.slow_down", "تمهل قليلًا.."), show_alert=True)

    ok, awarded = daily_claim(uid, amount=10)
    if not ok:
        await cb.answer(t(lang, "rewards.hub.daily_already", "أخذت نقاط اليوم بالفعل ✅"), show_alert=True)
    else:
        await cb.answer(t(lang, "rewards.hub.daily_ok", f"أُضيفت {awarded} نقطة ✅"), show_alert=True)
    await open_hub(cb, edit=True)

@router.callback_query(F.data == "rwd:hub:market")
async def cb_open_market(cb: CallbackQuery):
    # lazy import to avoid circulars
    from . import rewards_market as _mkt
    await _mkt.open_market(cb)

@router.callback_query(F.data == "rwd:hub:wallet")
async def cb_open_wallet(cb: CallbackQuery):
    from . import rewards_wallet as _w
    await _w.open_wallet(cb)
