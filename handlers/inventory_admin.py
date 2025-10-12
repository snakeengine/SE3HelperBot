from utils.admins import get_admin_ids, is_admin, get_owner_ids
# handlers/inventory_admin.py
from __future__ import annotations
import os, io, time, re
from pathlib import Path
from typing import List, Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile, Document
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from services import inventory as inv
from utils.paths import BASE  # Ù…Ø³Ø§Ø± data Ø§Ù„Ù…ÙˆØ­Ù‘Ø¯

router = Router(name="inventory_admin")

# ØµÙ„Ø§Ø­ÙŠØ§Øª
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = get_admin_ids() or [7360982123]
PRODUCT = os.getenv("PRODUCT_KEY", "8bp")

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# ---------------- Ø£Ø¯ÙˆØ§Øª ØªÙÙƒÙŠÙƒ Ù…ØªØ³Ø§Ù‡Ù„Ø© ----------------
INV_MIN_LEN = int(os.getenv("INV_MIN_LEN", "4"))  # Ø¹Ø¯Ù‘Ù„ Ø§Ù„Ø­Ø¯ Ø§Ù„Ø£Ø¯Ù†Ù‰ Ø¨Ø·ÙˆÙ„ Ø§Ù„Ù…ÙØªØ§Ø­ Ù…Ù† Ø§Ù„Ù…ØªØºÙŠØ±Ø§Øª Ø§Ù„Ø¨ÙŠØ¦ÙŠØ©

def _extract_loose(text: str, min_len: int = INV_MIN_LEN) -> List[str]:
    """
    ÙŠÙ‚Ø³Ù… Ø¹Ù„Ù‰ Ø§Ù„Ø£Ø³Ø·Ø± Ø£Ùˆ Ø§Ù„ÙÙˆØ§ØµÙ„ (, ;) ÙˆÙŠÙ‚Ø¨Ù„ Ø£ÙŠ Ù‚ÙŠÙ…Ø© Ø·ÙˆÙ„Ù‡Ø§ >= min_len.
    ÙŠØ²ÙŠÙ„ Ø§Ù„ØªÙƒØ±Ø§Ø±Ø§Øª Ù…Ø¹ Ø§Ù„Ø­ÙØ§Ø¸ Ø¹Ù„Ù‰ Ø§Ù„ØªØ±ØªÙŠØ¨.
    """
    if not text:
        return []
    parts = re.split(r"[,\n;]+", text.replace("\r", ""))
    seen, out = set(), []
    for p in parts:
        k = (p or "").strip()
        if len(k) >= min_len and k not in seen:
            seen.add(k); out.append(k)
    return out

async def _add_text_keys(product: str, days: int, text: str):
    """
    ÙŠØ¶ÙŠÙ Ù…ÙØ§ØªÙŠØ­ Ù…Ù† Ù†Øµ. ÙŠØ³ØªØ®Ø¯Ù… inv.add_keys_from_text Ø¥Ù† ÙˆÙØ¬Ø¯ØªØŒ
    ÙˆØ¥Ù„Ø§ ÙŠØ³ØªØ®Ø¯Ù… Ø§Ù„Ù…ÙØ­Ù„Ù‘Ù„ Ø§Ù„Ù…ØªØ³Ø§Ù‡Ù„ Ø¯Ø§Ø®Ù„ÙŠÙ‹Ø§.
    """
    fn = getattr(inv, "add_keys_from_text", None)
    if callable(fn):
        return await fn(product, days, text)
    # fallback
    lines = _extract_loose(text)
    return await inv.add_keys(product, days, lines)

# =============== FSM Ù„ØªØ±ÙÙŠØ¹ Ø§Ù„Ù…ÙØ§ØªÙŠØ­ ===============
class InvAddStates(StatesGroup):
    waiting_lines = State()

@router.message(Command("inv_stats"))
async def inv_stats_cmd(m: Message):
    if not _is_admin(m.from_user.id):
        return
    snap = await inv.snapshot_msg(PRODUCT)
    await m.answer(f"ðŸ§¾ Ø§Ù„Ù…Ø®Ø²ÙˆÙ†: {snap}")

async def _read_document_text(doc: Document, bot) -> Optional[str]:
    """ÙŠØ­Ø§ÙˆÙ„ ØªÙ†Ø²ÙŠÙ„ Ù…Ø³ØªÙ†Ø¯ (ÙŠÙØ¶Ù‘Ù„ .txt) ÙˆØ¥Ø±Ø¬Ø§Ø¹ Ù…Ø­ØªÙˆØ§Ù‡ ÙƒÙ†Øµ UTF-8."""
    try:
        buf = io.BytesIO()
        await bot.download(doc, buf)  # Aiogram 3
        return buf.getvalue().decode("utf-8", "ignore")
    except Exception:
        pass
    try:
        file = await bot.get_file(doc.file_id)
        buf = io.BytesIO()
        try:
            await bot.download_file(file.file_path, buf)
        except Exception:
            await bot.download(file, buf)
        return buf.getvalue().decode("utf-8", "ignore")
    except Exception:
        return None

@router.message(Command("inv_add"))
async def inv_add_start(m: Message, state: FSMContext):
    """
    Ø§Ù„Ø§Ø³ØªØ®Ø¯Ø§Ù…:
      1) Ø±Ø¯ Ø¹Ù„Ù‰ Ø±Ø³Ø§Ù„Ø© ÙÙŠÙ‡Ø§ Ø§Ù„Ù…ÙØ§ØªÙŠØ­ (Ù†Øµ/ÙƒØ§Ø¨ØªØ´Ù†/Ù…Ù„Ù .txt) Ø«Ù… Ø£Ø±Ø³Ù„: /inv_add 3
      2) Ø£Ùˆ Ø§Ø¨Ø¯Ø£ Ø¬Ù„Ø³Ø©: /inv_add 3  â† Ø£Ø±Ø³Ù„ Ø§Ù„Ù…ÙØ§ØªÙŠØ­ Ø¹Ù„Ù‰ Ø¯ÙØ¹Ø§Øª Ø«Ù… /done
      3) ØµÙŠØºØ©: /inv_add <product> <days>
    """
    if not _is_admin(m.from_user.id):
        return

    parts = (m.text or "").split()
    slug = PRODUCT
    days = None

    if len(parts) >= 2 and parts[1].isdigit():
        days = int(parts[1])
    elif len(parts) >= 3 and parts[2].isdigit():
        slug = parts[1]; days = int(parts[2])

    if days not in (3, 10, 30):
        await m.answer("â— Ø§Ø³ØªØ®Ø¯Ù…: /inv_add 3|10|30  (Ø£Ùˆ: /inv_add <product> <days>)")
        return

    # Ø±Ø¯ Ø¹Ù„Ù‰ Ø±Ø³Ø§Ù„Ø© Ù†Øµ/ÙƒØ§Ø¨ØªØ´Ù†
    if m.reply_to_message and (m.reply_to_message.text or m.reply_to_message.caption):
        raw = (m.reply_to_message.text or m.reply_to_message.caption or "")
        inserted, dup = await _add_text_keys(slug, days, raw)
        await m.answer(f"âœ… ØªÙ…Øª Ø§Ù„Ø¥Ø¶Ø§ÙØ©: {inserted} | Ù…ÙƒØ±Ø±Ø§Øª: {dup} | ({slug} - {days}d)")
        return

    # Ø±Ø¯ Ø¹Ù„Ù‰ Ø±Ø³Ø§Ù„Ø© ÙÙŠÙ‡Ø§ Ù…Ø³ØªÙ†Ø¯
    if m.reply_to_message and m.reply_to_message.document:
        doc = m.reply_to_message.document
        if (doc.mime_type or "").startswith("text") or (doc.file_name or "").lower().endswith(".txt"):
            text = await _read_document_text(doc, m.bot)
            if text is None:
                await m.answer("âš ï¸ ØªØ¹Ø°Ù‘Ø± Ù‚Ø±Ø§Ø¡Ø© Ø§Ù„Ù…Ø³ØªÙ†Ø¯. Ø£Ø±Ø³Ù„ Ø§Ù„Ù…ÙØ§ØªÙŠØ­ ÙƒÙ†Øµ Ø£Ùˆ Ù…Ù„Ù .txt.")
                return
            inserted, dup = await _add_text_keys(slug, days, text)
            await m.answer(f"âœ… ØªÙ…Øª Ø§Ù„Ø¥Ø¶Ø§ÙØ© Ù…Ù† Ù…Ù„Ù: {inserted} | Ù…ÙƒØ±Ø±Ø§Øª: {dup} | ({slug} - {days}d)")
            return

    # Ø¬Ù„Ø³Ø© Ø¥Ø¯Ø®Ø§Ù„ ÙŠØ¯ÙˆÙŠØ©
    await state.set_state(InvAddStates.waiting_lines)
    await state.update_data(slug=slug, days=days, buf="")
    await m.answer(
        f"âœï¸ Ø£Ø±Ø³Ù„ Ø§Ù„Ù…ÙØ§ØªÙŠØ­ (Ø³Ø·Ø± Ù„ÙƒÙ„ Ù…ÙØªØ§Ø­ Ø£Ùˆ Ù…ÙØµÙˆÙ„Ø© Ø¨ÙÙˆØ§ØµÙ„) Ø«Ù… Ø§ÙƒØªØ¨ /done\n"
        f"Ø§Ù„Ù…Ù†ØªØ¬: <code>{slug}</code> â€” Ø§Ù„Ù…Ø¯Ø©: <b>{days}d</b>",
        parse_mode="HTML"
    )

@router.message(InvAddStates.waiting_lines, F.text)
async def inv_add_collect(m: Message, state: FSMContext):
    if not _is_admin(m.from_user.id):
        return
    data = await state.get_data()
    buf: str = data.get("buf") or ""
    buf += "\n" + (m.text or "")
    await state.update_data(buf=buf)
    # Ù†Ø¹Ø±Ø¶ Ø¹Ø¯Ù‘Ù‹Ø§ ØªÙ‚Ø±ÙŠØ¨ÙŠÙ‹Ø§ Ù„Ù„Ù…ÙØ§ØªÙŠØ­ Ø§Ù„Ù…ÙƒØªØ´ÙØ© Ø­ØªÙ‰ Ø§Ù„Ø¢Ù†
    count_now = len(_extract_loose(buf))
    await m.answer(f"ðŸ“¥ ØªÙ… Ø§Ù„Ø§Ø³ØªÙ„Ø§Ù…. Ø§Ù„Ø¥Ø¬Ù…Ø§Ù„ÙŠ Ø§Ù„Ù…Ø¤Ù‚Øª: ~{count_now}")

@router.message(Command("done"))
async def inv_add_done(m: Message, state: FSMContext):
    if not _is_admin(m.from_user.id):
        return
    s = await state.get_state()
    if s != InvAddStates.waiting_lines:
        await m.answer("â„¹ï¸ Ù„Ø§ ØªÙˆØ¬Ø¯ Ø¬Ù„Ø³Ø© Ø±ÙØ¹ Ù†Ø´ÙØ·Ø©. Ø§Ø³ØªØ®Ø¯Ù… /inv_add Ø£ÙˆÙ„Ø§Ù‹.")
        return

    data = await state.get_data()
    slug = data.get("slug") or PRODUCT
    days = int(data.get("days") or 3)
    buf: str = data.get("buf") or ""

    if not _extract_loose(buf):
        await m.answer("Ù„Ø§ ØªÙˆØ¬Ø¯ Ù…ÙØ§ØªÙŠØ­ ØµØ§Ù„Ø­Ø© Ù„Ø¥Ø¶Ø§ÙØªÙ‡Ø§.")
        await state.clear()
        return

    inserted, dup = await _add_text_keys(slug, days, buf)
    await state.clear()
    await m.answer(f"âœ… ØªÙ…Øª Ø§Ù„Ø¥Ø¶Ø§ÙØ©: {inserted} | Ù…ÙƒØ±Ø±Ø§Øª: {dup} | ({slug} - {days}d)")

@router.message(Command("inv_dump"))
async def inv_dump_cmd(m: Message):
    """
    /inv_dump 3 [qty]
    /inv_dump <days> <qty> <product?>
    ÙŠØ³Ø­Ø¨ Ø§Ù„Ù…ÙØ§ØªÙŠØ­ ÙˆÙŠØ±Ø³Ù„Ù‡Ø§ ÙƒÙ…Ù„Ù Ù†ØµÙ‘ÙŠ ÙˆÙŠØ²ÙŠÙ„Ù‡Ø§ Ù…Ù† Ø§Ù„Ù…Ø®Ø²ÙˆÙ†.
    """
    if not _is_admin(m.from_user.id):
        return

    parts = (m.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await m.answer("â— Ø§Ø³ØªØ®Ø¯Ù…: /inv_dump 3|10|30 [qty]")
        return

    days = int(parts[1])
    if days not in (3, 10, 30):
        await m.answer("â— Ø§Ù„Ø£ÙŠØ§Ù… ÙŠØ¬Ø¨ Ø£Ù† ØªÙƒÙˆÙ† 3 Ø£Ùˆ 10 Ø£Ùˆ 30")
        return

    qty = 0
    prod = PRODUCT
    if len(parts) >= 3 and parts[2].isdigit():
        qty = int(parts[2])
    if len(parts) >= 4:
        prod = parts[3]

    keys = await inv.take(days=days, qty=qty, product=prod)
    if not keys:
        await m.answer("Ù„Ø§ ÙŠÙˆØ¬Ø¯ Ù…ÙØ§ØªÙŠØ­ Ù„Ø³Ø­Ø¨Ù‡Ø§.")
        return

    tmp_dir = BASE / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fname = tmp_dir / f"dump_{prod}_{days}d_{int(time.time())}.txt"
    fname.write_text("\n".join(keys) + "\n", encoding="utf-8")

    await m.answer_document(FSInputFile(str(fname)), caption=f"{prod} â€” {days}d â€” {len(keys)} key(s)")

