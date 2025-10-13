from __future__ import annotations

# handlers/alerts_user.py

import json, asyncio, time, datetime
from pathlib import Path
from typing import Dict, Any, List
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from lang import t, get_user_lang
from utils.alerts_broadcast import get_active_alerts
# أعلى الملف
from utils.alerts_policy import bump_signal
import os

# عطّل هذا الملف افتراضياً. لو احتجته مستقبلاً فعِّله بوضع ALERTS_V1=1
ALERTS_V1 = str(os.getenv("ALERTS_V1", "0")).lower() in {"1","true","yes","on"}

# إن لم يكن مفعلاً، لا تسجّل أي هاندلر بهذا الراوتر
if not ALERTS_V1:
    router = Router(name="alerts_user_disabled")
else:
    router = Router(name="alerts_user")

router = Router(name="alerts_user")

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
USERBOX_FILE = DATA_DIR / "alerts_userbox.json"   # { "<uid>": {"seen":[...], "ignored":[...], "deleted":[...] } }

# ---------- storage helpers ----------
# قفل بسيط لتفادي تضارب الكتابة المتزامنة
import threading as _th
_LOCK = _th.Lock()

def _jload(path: Path) -> dict:
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return {}

def _jsave(path: Path, data: dict) -> None:
    # كتابة ذرّية لتفادي تلف الملف عند الإنهاء المفاجئ
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def _state(uid: int) -> Dict[str, List[str]]:
    with _LOCK:
        db = _jload(USERBOX_FILE)
        s = db.get(str(uid)) or {}
        s.setdefault("seen", []); s.setdefault("ignored", []); s.setdefault("deleted", [])
        return s

def _save_state(uid: int, s: Dict[str, List[str]]) -> None:
    with _LOCK:
        db = _jload(USERBOX_FILE)
        db[str(uid)] = s
        _jsave(USERBOX_FILE, db)

# ---------- ui helpers ----------
def _kind_display(kind: str, lang: str) -> str:
    return t(lang, f"alerts.type.{kind}") or kind

def _list_keyboard(items: List[Dict[str, Any]], lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for it in items[:10]:
        label = (t(lang, "alerts.user.open_kind") or "Open {kind}").replace("{kind}", _kind_display(it["kind"], lang))
        kb.button(text=label, callback_data=f"inb:open:{it['id']}")
    kb.adjust(1)
    return kb

def _detail_keyboard(alert_id: str, lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "alerts.user.remind") or "Remind", callback_data=f"inb:remenu:{alert_id}")
    kb.button(text=t(lang, "alerts.user.ignore") or "Ignore", callback_data=f"inb:ignore:{alert_id}")
    kb.button(text=t(lang, "alerts.user.delete") or "Delete", callback_data=f"inb:delete:{alert_id}")
    kb.button(text=t(lang, "alerts.user.back") or "Back", callback_data="inb:back")
    kb.adjust(2,2)
    return kb

def _reminder_menu_kb(alert_id: str, lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "alerts.user.rem.10m") or "Remind in 10m", callback_data=f"inb:rem:{alert_id}:600")
    kb.button(text=t(lang, "alerts.user.rem.1h")  or "Remind in 1h",  callback_data=f"inb:rem:{alert_id}:3600")
    kb.button(text=t(lang, "alerts.user.rem.24h") or "Remind in 24h", callback_data=f"inb:rem:{alert_id}:86400")
    kb.button(text=t(lang, "alerts.user.back") or "Back", callback_data="inb:back")
    kb.adjust(1,1,1,1)
    return kb

async def _safe_edit_text(msg_or_cb, text: str, *, reply_markup=None):
    """تحرير آمن لتفادي TelegramBadRequest: message is not modified"""
    msg = msg_or_cb.message if isinstance(msg_or_cb, CallbackQuery) else msg_or_cb
    try:
        await msg.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

async def _schedule_reminder(cb_or_msg, uid: int, alert_id: str, delay: int, lang: str):
    """ينشئ تذكيرًا بعد مدة؛ يتأكد أن الإشعار ما زال صالحًا ولم يُفتح/يُتجاهل/يُحذف."""
    # حماية: لا نجعل التأخير خارج نطاق معقول
    delay = max(1, min(int(delay), 7 * 24 * 3600))  # حتى 7 أيام
    bot = cb_or_msg.bot

    async def _task():
        try:
            await asyncio.sleep(delay)
            # تحقق من الحالة الحالية
            st = _state(uid)
            if (alert_id in st.get("seen", [])
                or alert_id in st.get("ignored", [])
                or alert_id in st.get("deleted", [])):
                return
            items = get_active_alerts(lang)
            it = next((x for x in items if x["id"] == alert_id), None)
            if not it:
                return
            # أرسل التذكير
            kb = InlineKeyboardBuilder()
            label = (t(lang, "alerts.user.open_kind") or "Open {kind}").replace("{kind}", _kind_display(it["kind"], lang))
            kb.button(text=label, callback_data=f"inb:open:{alert_id}")
            kb.button(text=t(lang, "alerts.user.ignore") or "Ignore", callback_data=f"inb:ignore:{alert_id}")
            kb.adjust(1,1)
            await bot.send_message(
                uid,
                (t(lang, "alerts.user.remind_due") or "You have a pending alert"),
                reply_markup=kb.as_markup(),
                disable_web_page_preview=True
            )
        except Exception:
            # لا نفشل السايكلر بأكمله لو حدث استثناء
            return

    asyncio.create_task(_task())

# ---------- commands ----------
@router.message(Command("alerts", "inbox"))
async def alerts_inbox(msg: Message):
    lang = get_user_lang(msg.from_user.id) or "ar"
    st = _state(msg.from_user.id)
    items_all = get_active_alerts(lang)
    # استبعد المحذوف والمُتجاهَل
    ignored = set(st["ignored"]); deleted = set(st["deleted"])
    items = [it for it in items_all if it["id"] not in deleted and it["id"] not in ignored]
    if not items:
        return await msg.answer(t(lang, "alerts.user.box.empty") or "No active alerts.")
    count_unseen = len([it for it in items if it["id"] not in st["seen"]])
    header = (t(lang, "alerts.user.list.title") or "Your active alerts:") + f"\n{t(lang, 'alerts.user.count') or 'Count'}: {len(items)}"
    if count_unseen:
        header += f"\n{t(lang, 'alerts.user.unseen') or 'Unopened'}: {count_unseen}"
    kb = _list_keyboard(items, lang)
    await msg.answer(header, reply_markup=kb.as_markup())

@router.callback_query(F.data == "inb:back")
async def inb_back(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "ar"
    st = _state(cb.from_user.id)
    items_all = get_active_alerts(lang)
    ignored = set(st["ignored"]); deleted = set(st["deleted"])
    items = [it for it in items_all if it["id"] not in deleted and it["id"] not in ignored]
    if not items:
        await _safe_edit_text(cb, t(lang, "alerts.user.box.empty") or "No active alerts.")
        return await cb.answer()
    kb = _list_keyboard(items, lang)
    header = t(lang, "alerts.user.list.title") or "Your active alerts:"
    await _safe_edit_text(cb, header, reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data.regexp(r"^inb:open:(.+)$"))
async def inb_open(cb: CallbackQuery):
    bump_signal(cb.from_user.id, event="open")
    lang = get_user_lang(cb.from_user.id) or "ar"
    alert_id = cb.data.split(":", 2)[-1]
    items = get_active_alerts(lang)
    it = next((x for x in items if x["id"] == alert_id), None)
    if not it:
        return await cb.answer(t(lang, "alerts.user.expired") or "Alert expired.", show_alert=True)
    # علِّم كمقروء
    st = _state(cb.from_user.id)
    if alert_id not in st["seen"]:
        st["seen"].append(alert_id)
        _save_state(cb.from_user.id, st)
    # أرسل النص + مفاتيح الإجراءات
    kb = _detail_keyboard(alert_id, lang)
    await cb.message.answer(it["text"], reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data.regexp(r"^inb:ignore:(.+)$"))
async def inb_ignore(cb: CallbackQuery):
    bump_signal(cb.from_user.id, event="ignore")
    lang = get_user_lang(cb.from_user.id) or "ar"
    alert_id = cb.data.split(":", 2)[-1]
    st = _state(cb.from_user.id)
    if alert_id not in st["ignored"]:
        st["ignored"].append(alert_id)
        _save_state(cb.from_user.id, st)
    await cb.answer(t(lang, "alerts.user.ignored") or "Ignored", show_alert=False)
    await inb_back(cb)

@router.callback_query(F.data.regexp(r"^inb:delete:(.+)$"))
async def inb_delete(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "ar"
    alert_id = cb.data.split(":", 2)[-1]
    st = _state(cb.from_user.id)
    if alert_id not in st["deleted"]:
        st["deleted"].append(alert_id)
        _save_state(cb.from_user.id, st)
    await cb.answer(t(lang, "alerts.user.deleted") or "Deleted", show_alert=False)
    await inb_back(cb)

@router.callback_query(F.data.regexp(r"^inb:remenu:(.+)$"))
async def inb_reminder_menu(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "ar"
    alert_id = cb.data.split(":", 2)[-1]
    kb = _reminder_menu_kb(alert_id, lang)
    # تعديل آمن للكيبورد
    try:
        await cb.message.edit_reply_markup(reply_markup=kb.as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await cb.answer()

@router.callback_query(F.data.regexp(r"^inb:rem:(.+):(\d+)$"))
async def inb_reminder_set(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "ar"
    alert_id, delay = cb.data.split(":")[2], int(cb.data.split(":")[3])
    await _schedule_reminder(cb, cb.from_user.id, alert_id, delay, lang)
    await cb.answer(t(lang, "alerts.user.remind_set") or "Reminder set ✅", show_alert=False)
