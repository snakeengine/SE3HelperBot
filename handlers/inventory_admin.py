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
from utils.paths import BASE  # مسار data الموحّد

router = Router(name="inventory_admin")

# صلاحيات
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()] or [7360982123]
PRODUCT = os.getenv("PRODUCT_KEY", "8bp")

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# ---------------- أدوات تفكيك متساهلة ----------------
INV_MIN_LEN = int(os.getenv("INV_MIN_LEN", "4"))  # عدّل الحد الأدنى بطول المفتاح من المتغيرات البيئية

def _extract_loose(text: str, min_len: int = INV_MIN_LEN) -> List[str]:
    """
    يقسم على الأسطر أو الفواصل (, ;) ويقبل أي قيمة طولها >= min_len.
    يزيل التكرارات مع الحفاظ على الترتيب.
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
    يضيف مفاتيح من نص. يستخدم inv.add_keys_from_text إن وُجدت،
    وإلا يستخدم المُحلّل المتساهل داخليًا.
    """
    fn = getattr(inv, "add_keys_from_text", None)
    if callable(fn):
        return await fn(product, days, text)
    # fallback
    lines = _extract_loose(text)
    return await inv.add_keys(product, days, lines)

# =============== FSM لترفيع المفاتيح ===============
class InvAddStates(StatesGroup):
    waiting_lines = State()

@router.message(Command("inv_stats"))
async def inv_stats_cmd(m: Message):
    if not _is_admin(m.from_user.id):
        return
    snap = await inv.snapshot_msg(PRODUCT)
    await m.answer(f"🧾 المخزون: {snap}")

async def _read_document_text(doc: Document, bot) -> Optional[str]:
    """يحاول تنزيل مستند (يفضّل .txt) وإرجاع محتواه كنص UTF-8."""
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
    الاستخدام:
      1) رد على رسالة فيها المفاتيح (نص/كابتشن/ملف .txt) ثم أرسل: /inv_add 3
      2) أو ابدأ جلسة: /inv_add 3  ← أرسل المفاتيح على دفعات ثم /done
      3) صيغة: /inv_add <product> <days>
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
        await m.answer("❗ استخدم: /inv_add 3|10|30  (أو: /inv_add <product> <days>)")
        return

    # رد على رسالة نص/كابتشن
    if m.reply_to_message and (m.reply_to_message.text or m.reply_to_message.caption):
        raw = (m.reply_to_message.text or m.reply_to_message.caption or "")
        inserted, dup = await _add_text_keys(slug, days, raw)
        await m.answer(f"✅ تمت الإضافة: {inserted} | مكررات: {dup} | ({slug} - {days}d)")
        return

    # رد على رسالة فيها مستند
    if m.reply_to_message and m.reply_to_message.document:
        doc = m.reply_to_message.document
        if (doc.mime_type or "").startswith("text") or (doc.file_name or "").lower().endswith(".txt"):
            text = await _read_document_text(doc, m.bot)
            if text is None:
                await m.answer("⚠️ تعذّر قراءة المستند. أرسل المفاتيح كنص أو ملف .txt.")
                return
            inserted, dup = await _add_text_keys(slug, days, text)
            await m.answer(f"✅ تمت الإضافة من ملف: {inserted} | مكررات: {dup} | ({slug} - {days}d)")
            return

    # جلسة إدخال يدوية
    await state.set_state(InvAddStates.waiting_lines)
    await state.update_data(slug=slug, days=days, buf="")
    await m.answer(
        f"✍️ أرسل المفاتيح (سطر لكل مفتاح أو مفصولة بفواصل) ثم اكتب /done\n"
        f"المنتج: <code>{slug}</code> — المدة: <b>{days}d</b>",
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
    # نعرض عدًّا تقريبيًا للمفاتيح المكتشفة حتى الآن
    count_now = len(_extract_loose(buf))
    await m.answer(f"📥 تم الاستلام. الإجمالي المؤقت: ~{count_now}")

@router.message(Command("done"))
async def inv_add_done(m: Message, state: FSMContext):
    if not _is_admin(m.from_user.id):
        return
    s = await state.get_state()
    if s != InvAddStates.waiting_lines:
        await m.answer("ℹ️ لا توجد جلسة رفع نشِطة. استخدم /inv_add أولاً.")
        return

    data = await state.get_data()
    slug = data.get("slug") or PRODUCT
    days = int(data.get("days") or 3)
    buf: str = data.get("buf") or ""

    if not _extract_loose(buf):
        await m.answer("لا توجد مفاتيح صالحة لإضافتها.")
        await state.clear()
        return

    inserted, dup = await _add_text_keys(slug, days, buf)
    await state.clear()
    await m.answer(f"✅ تمت الإضافة: {inserted} | مكررات: {dup} | ({slug} - {days}d)")

@router.message(Command("inv_dump"))
async def inv_dump_cmd(m: Message):
    """
    /inv_dump 3 [qty]
    /inv_dump <days> <qty> <product?>
    يسحب المفاتيح ويرسلها كملف نصّي ويزيلها من المخزون.
    """
    if not _is_admin(m.from_user.id):
        return

    parts = (m.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await m.answer("❗ استخدم: /inv_dump 3|10|30 [qty]")
        return

    days = int(parts[1])
    if days not in (3, 10, 30):
        await m.answer("❗ الأيام يجب أن تكون 3 أو 10 أو 30")
        return

    qty = 0
    prod = PRODUCT
    if len(parts) >= 3 and parts[2].isdigit():
        qty = int(parts[2])
    if len(parts) >= 4:
        prod = parts[3]

    keys = await inv.take(days=days, qty=qty, product=prod)
    if not keys:
        await m.answer("لا يوجد مفاتيح لسحبها.")
        return

    tmp_dir = BASE / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fname = tmp_dir / f"dump_{prod}_{days}d_{int(time.time())}.txt"
    fname.write_text("\n".join(keys) + "\n", encoding="utf-8")

    await m.answer_document(FSInputFile(str(fname)), caption=f"{prod} — {days}d — {len(keys)} key(s)")
