# handlers/rewards_compat.py
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from .rewards_hub import open_hub

router = Router(name="rewards_compat")

@router.message(Command("rewards"))
async def cmd_rewards(m: Message):
    # compatibility: open the new hub
    await open_hub(m)
