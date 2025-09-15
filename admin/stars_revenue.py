# admin/stars_revenue.py
from __future__ import annotations
import os, json, time
from pathlib import Path
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.types import FSInputFile
router = Router(name="stars_revenue_admin")

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
ORDERS_FILE = DATA_DIR / "orders.jsonl"

def _admins() -> set[int]:
    raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
    ids = {int(x) for x in raw.split(",") if x.strip().isdigit()}
    return ids or {7360982123}  # احتياطي

ADMINS = _admins()

@router.message(Command("revenue"))
async def revenue(msg: Message):
    if msg.from_user.id not in ADMINS:
        return await msg.answer("Admins only.")
    if not ORDERS_FILE.exists():
        return await msg.answer("لا توجد عمليات بعد.")

    # يسمح بـ /revenue 30 = آخر 30 يوم
    try:
        days = int((msg.text or "").split(maxsplit=1)[1])
    except Exception:
        days = None
    since = int(time.time()) - days*86400 if days else 0

    total_xtr, n_xtr = 0, 0
    per_plan = {}
    with ORDERS_FILE.open("r", encoding="utf-8") as f:
        for ln in f:
            try: j = json.loads(ln)
            except: continue
            if j.get("status") != "paid": continue
            if j.get("currency") != "XTR": continue
            if j.get("ts", 0) < since: continue
            amt = int(j.get("total") or j.get("amount") or 0)
            total_xtr += amt; n_xtr += 1
            plan = str(j.get("plan") or "?")
            per_plan[plan] = per_plan.get(plan, 0) + amt

    lines = [f"📊 أرباح النجوم{' (آخر '+str(days)+' يوم)' if days else ''}:"]
    lines += [f"• إجمالي XTR: {total_xtr}", f"• عدد الدفعات: {n_xtr}"]
    if n_xtr: lines.append(f"• متوسط لكل دفعة: ~ {total_xtr//n_xtr} XTR")
    if per_plan:
        lines.append("• حسب الخطة:")
        for k,v in per_plan.items():
            lines.append(f"  - {k}: {v} XTR")
    await msg.answer("\n".join(lines))

@router.message(Command("revenue_csv"))
async def revenue_csv(msg: Message):
    if msg.from_user.id not in ADMINS:
        return await msg.answer("Admins only.")
    if not ORDERS_FILE.exists():
        return await msg.answer("لا توجد عمليات بعد.")
    import csv, tempfile, time, json
    rows = [("ts","currency","amount","plan","oid")]
    with ORDERS_FILE.open("r", encoding="utf-8") as f:
        for ln in f:
            try: j = json.loads(ln)
            except: continue
            if j.get("status")!="paid": continue
            rows.append((j.get("ts"), j.get("currency"), j.get("total") or j.get("amount"),
                         j.get("plan"), j.get("oid")))
    with tempfile.NamedTemporaryFile("w", delete=False, newline="", suffix=".csv", encoding="utf-8") as tf:
        cw = csv.writer(tf); cw.writerows(rows); path=tf.name
    await msg.answer_document(FSInputFile(path), caption="SEVIP revenue (paid orders)")