from __future__ import annotations

# handlers/debug_storage.py

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from utils.paths import safe_join, BASE, PROJECT_ROOT
from datetime import datetime

router = Router(name="debug_storage")

@router.message(Command("where"))
async def where(m: Message):
    await m.answer(
        "📁 BASE = <code>{}</code>\n📁 PROJECT_ROOT = <code>{}</code>".format(BASE, PROJECT_ROOT)
        , disable_web_page_preview=True
    )

@router.message(Command("save_test"))
async def save_test(m: Message):
    p = safe_join("debug", "persist.txt")
    p.write_text("saved at: {}\nby: {}\n".format(datetime.utcnow().isoformat()+"Z", m.from_user.id), encoding="utf-8")
    await m.answer(f"✅ Saved to: <code>{p}</code>")

@router.message(Command("read_test"))
async def read_test(m: Message):
    p = safe_join("debug", "persist.txt")
    if p.exists():
        await m.answer("📖 File:\n<code>{}</code>\n\n{}".format(p, p.read_text(encoding="utf-8")))
    else:
        await m.answer("❌ No file yet. Run /save_test first.")

@router.message(Command("wipe_test"))
async def wipe_test(m: Message):
    p = safe_join("debug", "persist.txt")
    try:
        if p.exists():
            p.unlink()
        await m.answer("🧹 wiped.")
    except Exception as e:
        await m.answer(f"⚠️ {e}")
