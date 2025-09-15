# handlers/sevip_store.py
from __future__ import annotations

import os, time, json, re, logging
from pathlib import Path
from typing import Dict, Any, Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

# ===== ترجمة آمنة =====
try:
    from lang import t as _t, get_user_lang as _get_user_lang
except Exception:
    def _t(_l, _k, fb=""): return fb or _k
    def _get_user_lang(_uid: int) -> str: return "ar"

log = logging.getLogger(__name__)
router = Router(name="sevip_store")

# ===== مسارات بيانات عامة =====
DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)

# ===== جسر VIP (يستخدم utils.vip_store إن وُجد؛ وإلا تخزين محلي) =====
try:
    from utils.vip_store import is_vip as _is_vip, get_expiry_ts as _get_expiry_ts, add_vip_days as _add_vip_days
except Exception:
    _VIP_FILE = DATA_DIR / "vip_users.json"
    def _vip_load() -> Dict[str, Any]:
        if _VIP_FILE.exists():
            try: return json.loads(_VIP_FILE.read_text(encoding="utf-8"))
            except Exception: return {}
        return {}
    def _vip_save(d: Dict[str, Any]) -> None:
        tmp = _VIP_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_VIP_FILE)
    def _get_expiry_ts(uid: int) -> Optional[int]:
        box = _vip_load(); item = box.get(str(uid))
        return int(item.get("expiry_ts")) if isinstance(item, dict) and "expiry_ts" in item else None
    def _is_vip(uid: int) -> bool:
        now = int(time.time()); exp = _get_expiry_ts(uid)
        return bool(exp and exp > now)
    def _add_vip_days(uid: int, days: int) -> int:
        now = int(time.time())
        box = _vip_load()
        cur = int(box.get(str(uid), {}).get("expiry_ts") or 0)
        base = max(now, cur)
        new_exp = base + days * 86400
        box[str(uid)] = {"expiry_ts": new_exp}
        _vip_save(box)
        return new_exp

# ===== الوصول إلى صناديق الأكواد (inventory) =====
try:
    from utils.sevip_store_box import inv_load, inv_save, inv_stats
except Exception:
    # طوارئ: لو ما توفر الموديول
    def inv_load() -> Dict[str, Any]:
        path = DATA_DIR / "sevip_inventory.json"
        if path.exists():
            try: return json.loads(path.read_text(encoding="utf-8"))
            except Exception: pass
        return {"boxes": {"3": [], "10": [], "30": []}}
    def inv_save(d: Dict[str, Any]) -> None:
        path = DATA_DIR / "sevip_inventory.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    def inv_stats() -> Dict[int, int]:
        d = inv_load(); out = {}
        for k, arr in d.get("boxes", {}).items():
            out[int(k)] = sum(1 for x in arr if x.get("status") == "unused")
        return out

# ===== حالات FSM لتفعيل كود =====
class ActStates(StatesGroup):
    waiting_key = State()

# ===== أدوات واجهة =====
def _kb(*rows) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for r in rows: kb.row(*r)
    return kb.as_markup()

def _menu_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=_t(lang, "sevip.menu.buy_usdt", "🛒 شراء عبر USDT (TRC20)"), callback_data="sevip:buy")
    b.button(text=_t(lang, "sevip.menu.activate", "🔑 تفعيل اشتراك"), callback_data="sevip:act")
    b.button(text=_t(lang, "sevip.menu.status", "📅 حالة الاشتراك"), callback_data="sevip:status")
    b.adjust(1, 2)
    return b.as_markup()

# ===== شاشة الدخول للمتجر/التفعيل =====
@router.callback_query(F.data == "shop:sevip")
async def open_shop(cq: CallbackQuery, state: FSMContext):
    lang = _get_user_lang(cq.from_user.id)
    st = inv_stats()
    stock_line = f"{_t(lang,'sevip.stock','المتوفر')} → 3d={st.get(3,0)}, 10d={st.get(10,0)}, 30d={st.get(30,0)}"
    await cq.message.answer(
        _t(lang, "sevip.menu.title", "شراء/تنشيط اشتراك SEVIP") + f"\n{stock_line}",
        reply_markup=_menu_kb(lang)
    )
    await cq.answer()

@router.message(Command("sevip"))
async def cmd_sevip(msg: Message, state: FSMContext):
    lang = _get_user_lang(msg.from_user.id)
    st = inv_stats()
    stock_line = f"{_t(lang,'sevip.stock','المتوفر')} → 3d={st.get(3,0)}, 10d={st.get(10,0)}, 30d={st.get(30,0)}"
    await msg.answer(_t(lang, "sevip.menu.title", "شراء/تنشيط اشتراك SEVIP") + f"\n{stock_line}", reply_markup=_menu_kb(lang))

# ===== شراء عبر USDT: نحيل إلى الهاندلر الجديد =====
@router.callback_query(F.data == "sevip:buy")
async def forward_to_usdt(cq: CallbackQuery):
    # هذا الكولباك تتعامل معه handlers/sevip_shop.py (show_buy)
    # هنا فقط نعيد استخدامه لبدء شاشة الشراء.
    # لو ما تم تضمين الهاندلر، نطبع رسالة.
    try:
        # نرسل كولباك افتراضي للمستخدم ليفتح شاشة الشراء
        from handlers.sevip_shop import show_buy  # type: ignore
        await show_buy(cq)
    except Exception:
        lang = _get_user_lang(cq.from_user.id)
        await cq.message.answer(_t(lang, "sevip.usdt.missing", "وحدة الشراء عبر USDT غير محمّلة."))
        await cq.answer()

# ===== تفعيل كود من الصناديق =====
KEY_PATTERN = re.compile(r"[A-Z0-9\-]{6,64}")

def _consume_code_from_inventory(code: str, uid: int) -> Optional[int]:
    """
    يبحث عن الكود داخل صناديق الأكواد:
      - إن كان موجوداً وغير مستخدم → يعلّمه 'redeemed' ويحفظ ويُرجع الأيام (3/10/30).
      - إن لم يوجد/مستخدم → يرجّع None.
    """
    d = inv_load()
    boxes = d.get("boxes", {})
    for days_key, arr in boxes.items():
        for item in arr:
            if (item.get("code") or "").upper() == code:
                if item.get("status") != "unused":
                    return None
                item["status"] = "redeemed"
                item["redeemed_by"] = uid
                item["redeemed_at"] = int(time.time())
                inv_save(d)
                try:
                    return int(days_key)
                except Exception:
                    return None
    return None

@router.callback_query(F.data == "sevip:act")
async def start_activation(cq: CallbackQuery, state: FSMContext):
    lang = _get_user_lang(cq.from_user.id)
    await state.set_state(ActStates.waiting_key)
    await cq.message.answer(_t(lang, "sevip.prompt.enter_key", "أرسل/ألصق كود التنشيط الآن (مثال: SE3-ABCD-1234-XYZ9)."))
    await cq.answer()

@router.message(ActStates.waiting_key)
async def receive_key(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    lang = _get_user_lang(uid)
    raw = (msg.text or "").strip().upper()
    m = KEY_PATTERN.search(raw)
    if not m:
        await msg.reply(_t(lang, "sevip.activate.bad_format", "صيغة الكود غير صحيحة. حاول مجددًا."))
        return
    key = m.group(0)

    days = _consume_code_from_inventory(key, uid)
    if not days:
        await msg.reply(_t(lang, "sevip.activate.not_found", "الكود غير موجود أو تم استخدامه."))
        return

    # أضف الأيام لعضوية المستخدم
    new_exp = _add_vip_days(uid, days)
    exp_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(new_exp))
    await state.clear()
    await msg.reply(_t(lang, "sevip.activate.ok", f"تم التفعيل ✅\nتمت إضافة {days} يومًا.\nينتهي في: {exp_str}"))

# ===== حالة الاشتراك =====
@router.callback_query(F.data == "sevip:status")
async def status_view(cq: CallbackQuery):
    uid = cq.from_user.id
    lang = _get_user_lang(uid)
    exp = _get_expiry_ts(uid)
    if exp and exp > int(time.time()):
        exp_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(exp))
        await cq.message.answer(_t(lang, "sevip.status.active_until", f"اشتراكك نشِط حتى: {exp_str} ✅"))
    else:
        await cq.message.answer(_t(lang, "sevip.status.not_active", "لا يوجد اشتراك نشِط حاليًا."))
    await cq.answer()
