# handlers/trusted_suppliers.py
from __future__ import annotations

import os, json
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from lang import t, get_user_lang

router = Router(name="trusted_suppliers")

DATA_DIR = "data"
PUB_FILE = os.path.join(DATA_DIR, "public_suppliers.json")

PER_PAGE = 6

def _load_public() -> list[dict]:
    try:
        with open(PUB_FILE, "r", encoding="utf-8") as f:
            arr = json.load(f)
            return arr if isinstance(arr, list) else []
    except Exception:
        return []

def _paginate(items: list[dict], page: int, per_page: int = PER_PAGE):
    total = max(1, (len(items) + per_page - 1) // per_page)
    page = max(1, min(page, total))
    start = (page - 1) * per_page
    return items[start:start + per_page], page, total

def _kb_list(lang: str, page_items: list[dict], page: int, total: int):
    rows = []
    for d in page_items:
        name = (d.get("name") or d.get("username") or str(d.get("user_id"))).strip()
        country = (d.get("country") or "").strip()
        label = f"{name} — {country}" if country else name
        rows.append([InlineKeyboardButton(text=label, callback_data=f"ts:view:{int(d.get('user_id', 0))}")])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="«", callback_data=f"ts:list:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{total}", callback_data="noop"))
    if page < total:
        nav.append(InlineKeyboardButton(text="»", callback_data=f"ts:list:{page+1}"))
    rows.append(nav)

    rows.append([InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _kb_card(lang: str, d: dict):
    rows = []
    contact = (d.get("contact") or "").strip()
    if contact:
        if contact.startswith("@"):
            url = f"https://t.me/{contact.lstrip('@')}"
        elif contact.isdigit():
            # لو رقم، نخلي زر فقط يفتح تيليجرام بالآيدي (إن توافر)
            url = f"tg://user?id={int(d.get('user_id', 0))}"
        else:
            url = contact  # رابط خارجي
        rows.append([InlineKeyboardButton(text=t(lang, "ts_contact_btn"), url=url)])

    channel = (d.get("channel") or "").strip()
    if channel:
        url = channel if channel.startswith("http") else f"https://t.me/{channel.lstrip('@')}"
        rows.append([InlineKeyboardButton(text=t(lang, "ts_channel_btn"), url=url)])

    rows.append([InlineKeyboardButton(text=t(lang, "ts_back_to_list"), callback_data="trusted_suppliers")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data == "trusted_suppliers")
async def ts_open(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    items = _load_public()
    if not items:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data="back_to_menu")]
        ])
        await cb.message.edit_text(t(lang, "ts_empty"), reply_markup=kb)
        return await cb.answer()
    page_items, page, total = _paginate(items, 1)
    await cb.message.edit_text(t(lang, "ts_list_title"), reply_markup=_kb_list(lang, page_items, page, total))
    await cb.answer()

@router.callback_query(F.data.regexp(r"^ts:list:\d+$"))
async def ts_list(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    page = int(cb.data.split(":")[2])
    items = _load_public()
    if not items:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data="back_to_menu")]
        ])
        await cb.message.edit_text(t(lang, "ts_empty"), reply_markup=kb)
        return await cb.answer()
    page_items, p, total = _paginate(items, page)
    await cb.message.edit_text(t(lang, "ts_list_title"), reply_markup=_kb_list(lang, page_items, p, total))
    await cb.answer()

@router.callback_query(F.data.regexp(r"^ts:view:\d+$"))
async def ts_view(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    uid = int(cb.data.split(":")[2])
    items = _load_public()
    d = next((x for x in items if int(x.get("user_id", 0)) == uid), None)
    if not d:
        return await cb.answer(t(lang, "not_found"), show_alert=True)

    text = (
        f"🧑‍💻 <b>{t(lang, 'ts_card_title')}</b>\n"
        f"{t(lang, 'spub_field_name')}: <b>{d.get('name','')}</b>\n"
        f"{t(lang, 'spub_field_country')}: <b>{d.get('country','')}</b>\n"
        f"{t(lang, 'spub_field_contact')}: <code>{d.get('contact','')}</code>\n"
        f"{t(lang, 'spub_field_channel')}: <code>{d.get('channel','')}</code>"
    )
    bio = (d.get("bio") or "").strip()
    if bio:
        text += f"\n{t(lang, 'spub_field_bio')}: {bio}"

    await cb.message.edit_text(text, reply_markup=_kb_card(lang, d), disable_web_page_preview=True)
    await cb.answer()

@router.callback_query(F.data == "noop")
async def _noop(cb: CallbackQuery):
    await cb.answer()
