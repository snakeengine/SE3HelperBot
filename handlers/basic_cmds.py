# handlers/basic_cmds.py
from __future__ import annotations
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from lang import t, get_user_lang

router = Router(name="basic_cmds")

@router.message(Command("help"))
async def cmd_help(m: Message):
    lang = get_user_lang(m.from_user.id) or "ar"
    await m.answer(
        t(lang, "help.text") or
        "ℹ️ <b>Help</b>\nAvailable commands:\n/start – start the bot\n/help – show help\n/about – about this bot\n/report – report an issue\n/language – change language",
        disable_web_page_preview=True,
    )

@router.message(Command("about"))
async def cmd_about(m: Message):
    lang = get_user_lang(m.from_user.id) or "ar"
    await m.answer(
        t(lang, "about.text") or
        "🤖 <b>About</b>\nThis is the S.E Support bot.",
        disable_web_page_preview=True,
    )

@router.message(Command("report"))
async def cmd_report(m: Message):
    lang = get_user_lang(m.from_user.id) or "ar"
    await m.answer(
        t(lang, "report.text") or
        "🛠️ <b>Report</b>\nSend your issue here and we’ll take a look.",
        disable_web_page_preview=True,
    )

@router.message(Command("language"))
async def cmd_language(m: Message):
    lang = get_user_lang(m.from_user.id) or "ar"
    await m.answer(
        t(lang, "language.text") or
        "🌐 <b>Language</b>\nUse /language to change your language.",
        disable_web_page_preview=True,
    )
