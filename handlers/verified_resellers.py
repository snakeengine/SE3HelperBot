# 📁 handlers/verified_resellers.py
from __future__ import annotations

import os, json, math
from pathlib import Path
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.filters import Command
from lang import t, get_user_lang

router = Router(name="verified_resellers")

# ====== الإعدادات ======
ENV_PATH = os.getenv("VERIFIED_RESELLERS_FILE", "").strip()
DATA_FILE = Path(ENV_PATH) if ENV_PATH else Path("data") / "verified_resellers.json"
PAGE_SIZE = 8  # شبكة 2×4

# قائمة احتياطية افتراضية (fallback)
FALLBACK = [
    {"name": "TPlayz1",          "username": "TPlayz1"},
    {"name": "SHADOW XD YT",     "username": "SHADOW_XD_YT"},
    {"name": "hvmods",           "username": "hvmods"},
    {"name": "Zyugaming99",      "username": "Zyugaming99"},
    {"name": "Lotfy8bp",         "username": "Lotfy8bp"},
    {"name": "RoyalGaming047",   "username": "RoyalGaming047"},
    {"name": "Dragon 8Bp",       "username": "Dragon_8Bp"},
    {"name": "GAMINGTECH10",     "username": "GAMINGTECH10"},
    {"name": "Bayuo official",   "username": "Bayuo_officiaL"},
    {"name": "AlexMods79",       "username": "AlexMods79"},
    {"name": "Enzogaming007",    "username": "Enzogaming007"},
    {"name": "antonio m oficial","username": "antonio_m_oficial"},
    {"name": "GamingLife048",    "username": "GamingLife048"},
    {"name": "rakesh8bpyt",      "username": "rakesh8bpyt"},
    {"name": "Helpmebropls",     "username": "Helpmebropls"},
    {"name": "Tayyab78621",      "username": "Tayyab78621"},
    {"name": "Mela 8ball",       "username": "Mela_8ball"},
    {"name": "SmartGaming44",    "username": "SmartGaming44"},
    {"name": "khanbaba8bp",      "username": "khanbaba8bp"},
    {"name": "Pro iQ1",          "username": "Pro_iQ1"},
]

# ====== CB IDs ======
OPEN_LIST_CB   = "btn_verified_resellers"
DETAIL_CB_PREF = "resel:"
NOOP_CB        = "noop"
BACK_TO_MENU   = "back_to_menu"

# ====== ترجمات مساعدة ======
def _tr(lang: str, key: str, default: str) -> str:
    val = t(lang, key)
    return val if val != key else default

# ====== تحميل وتنظيف البيانات ======
def _safe_load_json(path: Path) -> list[dict]:
    try:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []

def _normalize_username(u: str) -> str:
    return (u or "").strip().lstrip("@")

def load_resellers() -> list[dict]:
    """
    تحميل البائعين مع الحفاظ على ترتيبهم كما هو في الملف.
    يدعم rank/order اختياريًا. يزيل التكرارات ويُطبّع usernames.
    """
    try:
        raw = _safe_load_json(DATA_FILE) or FALLBACK
        seen = set()
        cleaned = []

        for idx, r in enumerate(raw):
            u = _normalize_username(r.get("username", ""))
            if not u or u.lower() in seen:
                continue
            seen.add(u.lower())

            name = (r.get("name") or u).strip()
            rank = r.get("rank", r.get("order", idx))
            cleaned.append({"name": name, "username": u, "rank": rank})

        # فرز مستقر حسب rank (الأرقام أولًا)، ثم الإبقاء على ترتيب الإدراج
        cleaned.sort(key=lambda x: (0 if isinstance(x["rank"], (int, float)) else 1, x["rank"]))
        return [{"name": c["name"], "username": c["username"]} for c in cleaned]
    except Exception:
        return FALLBACK

# ====== الرسائل ولوحات الأزرار ======
def title_text(lang: str) -> str:
    return _tr(
        lang, "resellers_title",
        "✅ <b>Verified Resellers</b>\nPick a seller to view details or start chat."
    )

def empty_text(lang: str) -> str:
    return _tr(
        lang, "vipub_no_users", "— No resellers —"
    )

def list_keyboard(lang: str, page: int) -> InlineKeyboardMarkup:
    items = load_resellers()
    if not items:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data=BACK_TO_MENU)]
        ])

    total_pages = max(1, math.ceil(len(items) / PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    block = items[start:start + PAGE_SIZE]

    rows: list[list[InlineKeyboardButton]] = []

    # أزرار التفاصيل (شبكة 2 × N)
    for i in range(0, len(block), 2):
        row: list[InlineKeyboardButton] = []
        for r in block[i:i+2]:
            label = f"{r['name']}"
            row.append(InlineKeyboardButton(
                text=label,
                callback_data=f"{DETAIL_CB_PREF}{r['username']}:{page}"
            ))
        rows.append(row)

    # أزرار التنقل
    if total_pages > 1:
        rows.append([
            InlineKeyboardButton(
                text=_tr(lang, "res_prev", "‹ Prev"),
                callback_data=f"{OPEN_LIST_CB}:{page-1}" if page > 0 else NOOP_CB
            ),
            InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data=NOOP_CB),
            InlineKeyboardButton(
                text=_tr(lang, "res_next", "Next ›"),
                callback_data=f"{OPEN_LIST_CB}:{page+1}" if page < total_pages-1 else NOOP_CB
            ),
        ])

    rows.append([InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data=BACK_TO_MENU)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def detail_text(lang: str, name: str, username: str) -> str:
    return (
        f"🛡️ <b>{_tr(lang,'reseller_profile','Verified Reseller')}</b>\n\n"
        f"• {_tr(lang,'reseller_name','Name')}: <b>{name}</b>\n"
        f"• {_tr(lang,'reseller_username','Username')}: <code>@{username}</code>\n\n"
        f"{_tr(lang,'reseller_hint','Tap the button to start a Telegram chat. Beware of imposters.')}"
    )

def detail_keyboard(lang: str, username: str, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=_tr(lang, "contact_on_telegram", "💬 Chat on Telegram"),
            url=f"https://t.me/{username}"
        )],
        [InlineKeyboardButton(
            text=_tr(lang, "back_to_list", "⬅️ Back to list"),
            callback_data=f"{OPEN_LIST_CB}:{page}"
        )],
        [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data=BACK_TO_MENU)],
    ])

# ====== الهاندلرات ======
@router.callback_query(F.data == OPEN_LIST_CB)
async def open_resellers(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    items = load_resellers()
    if not items:
        await cb.message.edit_text(
            f"{title_text(lang)}\n\n{empty_text(lang)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data=BACK_TO_MENU)]
            ]),
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    else:
        await cb.message.edit_text(
            title_text(lang),
            reply_markup=list_keyboard(lang, 0),
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    await cb.answer()

@router.callback_query(F.data.startswith(f"{OPEN_LIST_CB}:"))
async def paginate_resellers(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    try:
        page = int(cb.data.split(":", 1)[1])
    except Exception:
        page = 0
    await cb.message.edit_text(
        title_text(lang),
        reply_markup=list_keyboard(lang, page),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await cb.answer()

@router.callback_query(F.data.startswith(DETAIL_CB_PREF))
async def open_reseller_detail(cb: CallbackQuery):
    lang = get_user_lang(cb.from_user.id) or "en"
    # resel:<username>:<page?>
    parts = cb.data.split(":", 2)
    username = parts[1] if len(parts) > 1 else ""
    try:
        page = int(parts[2]) if len(parts) > 2 else 0
    except Exception:
        page = 0

    # جلب الاسم من القائمة
    r = next((x for x in load_resellers() if x["username"].lower() == username.lower()), None)
    name = r["name"] if r else (username or "—")

    await cb.message.edit_text(
        detail_text(lang, name, username),
        reply_markup=detail_keyboard(lang, username, page),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await cb.answer()

@router.callback_query(F.data == NOOP_CB)
async def noop(cb: CallbackQuery):
    await cb.answer()

# أمر اختياري
@router.message(Command("resellers"))
async def resellers_cmd(msg: Message):
    lang = get_user_lang(msg.from_user.id) or "en"
    items = load_resellers()
    if not items:
        await msg.answer(
            f"{title_text(lang)}\n\n{empty_text(lang)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "back_to_menu"), callback_data=BACK_TO_MENU)]
            ]),
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    else:
        await msg.answer(
            title_text(lang),
            reply_markup=list_keyboard(lang, 0),
            parse_mode="HTML",
            disable_web_page_preview=True
        )

