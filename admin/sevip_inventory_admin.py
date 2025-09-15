# admin/sevip_inventory_admin.py
from __future__ import annotations
import os, logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, ContentType, FSInputFile
from utils.sevip_store_box import inv_add_codes, inv_stats

router = Router(name="sevip_inventory_admin")
log = logging.getLogger(__name__)

_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if x.strip().isdigit()]

def _is_admin(uid: int) -> bool: return uid in ADMIN_IDS if ADMIN_IDS else False

@router.message(Command("inv_stats"))
async def cmd_stats(msg: Message):
    if not _is_admin(msg.from_user.id): return
    st = inv_stats()
    await msg.reply(f"المخزون:\n- 3d: {st.get(3,0)}\n- 10d: {st.get(10,0)}\n- 30d: {st.get(30,0)}")

@router.message(Command("inv_add"))
async def cmd_inv_add(msg: Message):
    if not _is_admin(msg.from_user.id): return
    parts = (msg.text or "").split()
    if len(parts) < 2 or parts[1] not in ("3","10","30"):
        await msg.reply("الاستخدام: /inv_add <3|10|30>\nثم أرسل الأكواد في رسالة تالية كل سطر كود.")
        return
    await msg.reply("أرسل الأكواد الآن (كل سطر كود واحد).")
    msg.bot["await_inv_add"] = {"uid": msg.from_user.id, "days": int(parts[1])}

@router.message()
async def inv_add_followup(msg: Message):
    ctx = msg.bot.get("await_inv_add")
    if not ctx: return
    if msg.from_user.id != ctx["uid"]: return
    codes = []
    for line in (msg.text or "").splitlines():
        val = line.strip()
        if val: codes.append(val)
    added = inv_add_codes(ctx["days"], codes, note=f"by {msg.from_user.id}")
    msg.bot["await_inv_add"] = None
    await msg.reply(f"تمت الإضافة: {added} كود لباقة {ctx['days']} يوم.")
