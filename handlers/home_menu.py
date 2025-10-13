# handlers/home_menu.py
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from datetime import datetime
from html import escape

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
)

from lang import t, get_user_lang

router = Router(name="home_menu")
log = logging.getLogger(__name__)

# ===== تخزين أول دخول للمستخدم =====
STARTED_FILE = Path("data/started_users.json")


def _load_started() -> dict:
    try:
        if STARTED_FILE.exists():
            return json.loads(STARTED_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def _save_started(d: dict) -> None:
    try:
        STARTED_FILE.parent.mkdir(parents=True, exist_ok=True)
        STARTED_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ===== خريطة CB موحّدة (مع فولباكات آمنة) =====
try:
    from handlers.start import CB as _CB
except Exception:
    _CB = None

CB = {
    "VIP_BUY_INTERNAL": "shop:sevip",
    "TRUSTED_SUPPLIERS": "trusted_suppliers",
    "BOT_OPEN": "bot:open",
}
if isinstance(_CB, dict):
    CB.update({k: _CB.get(k, v) for k, v in CB.items()})

# ===== لوحة إنلاين 3×3 (تُعرض فقط مع /start) =====
def main_menu_kb(lang: str) -> InlineKeyboardMarkup:
    L = (lang or "ar").startswith("ar")
    def LBL(ar, en): return ar if L else en

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=LBL("👤 المستخدم", "User 👤"),   callback_data="noop"),
            InlineKeyboardButton(text=LBL("🌟VIP", "VIP 🌟"),            callback_data="noop"),
            InlineKeyboardButton(text=LBL("🤖 البوت", "Bot 🤖"),         callback_data=CB["BOT_OPEN"]),
        ],
        [
            InlineKeyboardButton(text=LBL("👥 المجموعات", "Groups 👥"),  url="https://t.me/SnakeEngine2"),
            InlineKeyboardButton(text=LBL("📣 القنوات", "Channels 📣"),  url="https://t.me/SnakeEngine"),
            InlineKeyboardButton(text=LBL("💬 المنتديات", "Forums 💬"),  url="https://t.me/SnakeEngine1"),
        ],
    ])


# ===== أدوات التاريخ/العرض =====
def _fmt_dt(ts: float | int | str | None) -> str:
    if ts in (None, "", 0, "0"):
        return "—"
    try:
        if isinstance(ts, str):
            s = ts.strip()
            if s in ("", "0"):
                return "—"
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
            except Exception:
                ts = float(s)
        ts = float(ts)
        if ts <= 0:
            return "—"
        if ts > 10**12:
            ts /= 1000.0
        if ts < 1136073600:  # 2006-01-01
            return "—"
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


def _read_first_seen(uid: int) -> tuple[str | None, dict | int | float | str | None]:
    for p in ("data/started_users.json", "data/users.json"):
        path = Path(p)
        try:
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and str(uid) in data:
                return p, data[str(uid)]
        except Exception:
            continue
    return None, None


def _joined_at(uid: int) -> str:
    src, val = _read_first_seen(uid)
    if isinstance(val, dict):
        return _fmt_dt(val.get("ts") or val.get("time") or val.get("joined") or val.get("iso"))
    return _fmt_dt(val)


def _lang_name(uid: int) -> str:
    try:
        code = get_user_lang(uid) or "ar"
    except Exception:
        code = "ar"
    return {"ar": "العربية", "en": "English"}.get(code, code)


def _tr(lang: str, key: str, ar: str, en: str) -> str:
    try:
        val = t(lang, key)
        if val and val != key:
            return val
    except Exception:
        pass
    return ar if (lang or "ar").startswith("ar") else en


def _pm() -> dict:
    try:
        p = Path("data/public_meta.json")
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
    except Exception:
        pass
    return {}


def _normalize_first_seen(uid: int):
    try:
        data = _load_started()
        cur = data.get(str(uid))
        need_fix = False

        if cur is None:
            need_fix = True
        elif isinstance(cur, (int, float, str)):
            if _fmt_dt(cur) == "—":
                need_fix = True
            else:
                need_fix = True
        elif isinstance(cur, dict):
            disp = _fmt_dt(cur.get("ts") or cur.get("time") or cur.get("joined") or cur.get("iso"))
            if disp == "—":
                need_fix = True

        if need_fix:
            now_ts = int(time.time())
            data[str(uid)] = {"ts": now_ts, "iso": datetime.utcnow().isoformat()}
            _save_started(data)
    except Exception as e:
        log.warning("normalize first_seen failed: %s", e)


# ===== محتوى الأقسام =====
def section_text(key: str, user) -> str:
    uid = int(getattr(user, "id", 0) or 0)
    first = escape((getattr(user, "first_name", "") or "").strip())
    uname = getattr(user, "username", None)
    lang = get_user_lang(uid) or "ar"
    L = lang.startswith("ar")

    def LBL(ar, en):
        return ar if L else en

    if key == "bot":
        return LBL(
            "🤖 <b>عن البوت</b>\n"
            "• بوت الدعم والمساعدة Snake Engine.\n"
            "• أوامر سريعة: /start /help /report /language\n"
            "• القناة الرسمية: <a href='https://t.me/SnakeEngine'>@SnakeEngine</a>\n"
            "• المنتدى: <a href='https://t.me/SnakeEngine1'>اضغط هنا</a>\n",
            "🤖 <b>About the bot</b>\n"
            "• Support & helper bot for Snake Engine.\n"
            "• Quick commands: /start /help /report /language\n"
            "• Official channel: <a href='https://t.me/SnakeEngine'>@SnakeEngine</a>\n"
            "• Forum: <a href='https://t.me/SnakeEngine1'>open</a>\n",
        )

    if key == "premium":
        return LBL(
            "🌟 <b>VIP</b>\n"
            "• أولوية ردود الدعم.\n"
            "• حدود أعلى للطلبات.\n"
            "• مزايا إضافية عند توفرها.\n"
            "اختر طريقة الشراء:\n"
            "• «اشترِ الآن (USDT)» لتفعيل مباشر داخل النظام.\n"
            "• «اشترِ من موردينا» للشراء عبر موردينا الموثوقين.\n",
            "🌟 <b>Premium</b>\n"
            "• Priority support replies.\n"
            "• Higher usage limits.\n"
            "• Extra perks when available.\n"
            "Choose how to buy:\n"
            "• “Buy now (USDT)” for direct in-bot activation.\n"
            "• “Buy from our suppliers” via trusted sellers.\n",
        )

    if key == "user":
        _normalize_first_seen(uid)
        jid = _joined_at(uid)
        link = f"@{uname}" if uname else LBL("— لا يوجد اسم مستخدم —", "-- no username --")
        return LBL(
            f"👤 <b>معلومات المستخدم</b>\n"
            f"• الاسم: <code>{first}</code>\n"
            f"• المعرّف: <code>{uid}</code>\n"
            f"• اسم المستخدم: {link}\n"
            f"• اللغة: <code>{_lang_name(uid)}</code>\n"
            f"• تاريخ أول دخول للبوت: <code>{jid}</code>\n",
            f"👤 <b>User info</b>\n"
            f"• Name: <code>{first}</code>\n"
            f"• ID: <code>{uid}</code>\n"
            f"• Username: {link}\n"
            f"• Language: <code>{_lang_name(uid)}</code>\n"
            f"• First seen: <code>{jid}</code>\n",
        )

    if key == "group":
        return LBL(
            "👥 <b>المجموعات</b>\nرابط مجموعاتنا:\n<a href='https://t.me/SnakeEngine2'>https://t.me/SnakeEngine2</a>\n",
            "👥 <b>Groups</b>\nJoin our groups:\n<a href='https://t.me/SnakeEngine2'>https://t.me/SnakeEngine2</a>\n",
        )

    if key == "channel":
        return LBL(
            "📣 <b>القنوات</b>\nالقناة الرسمية:\n<a href='https://t.me/SnakeEngine'>https://t.me/SnakeEngine</a>\n",
            "📣 <b>Channels</b>\nOfficial channel:\n<a href='https://t.me/SnakeEngine'>https://t.me/SnakeEngine</a>\n",
        )

    if key == "forum":
        return LBL(
            "💬 <b>المنتديات</b>\nمنتدانا:\n<a href='https://t.me/SnakeEngine1'>https://t.me/SnakeEngine1</a>\n",
            "💬 <b>Forums</b>\nOur forum:\n<a href='https://t.me/SnakeEngine1'>https://t.me/SnakeEngine1</a>\n",
        )

    return LBL("❕ لا يوجد محتوى لهذا القسم.", "❕ No content for this section.")


# ===== واجهة موحّدة: ترجع (النص + كيبورد) =====
def section_render(key: str, user) -> tuple[str, InlineKeyboardMarkup | None]:
    uid = int(getattr(user, "id", 0) or 0)
    lang = get_user_lang(uid) or "ar"
    L = lang.startswith("ar")

    def LBL(ar, en):
        return ar if L else en

    body = section_text(key, user) or ""
    kb: InlineKeyboardMarkup | None = None

    if key == "bot":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=LBL("فتح لوحة البوت", "Open bot panel"),
                                      callback_data=CB.get("BOT_OPEN", "bot:open"))]
            ]
        )

    if key == "premium":
        forum = _pm().get("forum") or "https://t.me/SnakeEngine2/1"
        rows = [
            [InlineKeyboardButton(
                text=_tr(lang, "premium.btn.buy_internal", "🛒 اشترِ الآن (USDT)", "🛒 Buy now (USDT)"),
                callback_data=CB.get("VIP_BUY_INTERNAL", "shop:sevip"),
            )],
            [InlineKeyboardButton(
                text=_tr(lang, "premium.btn.buy_suppliers", "🛒 اشترِ من موردينا", "🛒 Buy from suppliers"),
                callback_data=CB.get("TRUSTED_SUPPLIERS", "trusted_suppliers"),
            )],
            [InlineKeyboardButton(
                text=_tr(lang, "ui.forum", "💬 المنتدى", "💬 Forum"),
                url=forum,
            )],
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=rows)

    return body, kb


# ===== /start =====
@router.message(CommandStart())
async def on_start(m: Message):
    _normalize_first_seen(m.from_user.id)
    lang = get_user_lang(m.from_user.id) or "ar"
    await m.answer(
        (t(lang, "start.hello") or "Hi Welcome To the bot 👋"),
        reply_markup=main_menu_kb(lang),
        disable_web_page_preview=True,
    )


# امنع “جاري التحميل…” لأزرار معلوماتية
@router.callback_query(F.data.in_({"noop", "my_forum_info"}))
async def cb_noop(c: CallbackQuery):
    await c.answer()
    return
