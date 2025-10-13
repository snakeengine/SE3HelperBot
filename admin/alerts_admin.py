from __future__ import annotations

from utils.admins import get_admin_ids, is_admin, get_owner_ids
# admin/alerts_admin.py


import os, time, datetime, secrets
from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, ForceReply
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from utils.alerts_broadcast import get_active_alerts
from utils.alerts_broadcast import ACTIVE_FILE  # Ø¨Ø¬Ø§Ù†Ø¨ Ø¨Ù‚ÙŠØ© Ø§Ù„Ø§Ø³ØªÙŠØ±Ø§Ø¯Ø§Øª Ù…Ù† alerts_broadcast

from lang import t, get_user_lang
import json, time
# Ø§Ù„Ù†Ø¸Ø§Ù… Ø§Ù„Ø¬Ø¯ÙŠØ¯: ØªØ®Ø²ÙŠÙ†/Ø¨Ø«/Ø¥ØØµØ§Ø¡Ø§Øª
from utils.alerts_broadcast import _load_json, _save_json, STATS_FILE, broadcast
# Ø§Ù„Ù†Ø¸Ø§Ù… Ø§Ù„Ø¬Ø¯ÙŠØ¯: Ø§Ù„Ø¬Ø¯ÙˆÙ„Ø©
from utils.alerts_scheduler import enqueue_job, list_jobs, cancel_job, cancel_all_jobs
# Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª Ø³ÙŠØ§Ø³Ø© Ø§Ù„Ø¨Ø«
from utils.alerts_config import get_config, set_config

router = Router(name="alerts_admin")

# ====================== Ø¥Ø¹Ø¯Ø§Ø¯ Ø¹Ø§Ù… ======================
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = get_admin_ids()
if not ADMIN_IDS:
    ADMIN_IDS = get_admin_ids()  # Ø§ÙØªØ±Ø§Ø¶ÙŠ Ø¹Ù†Ø¯ Ø¹Ø¯Ù… Ø¶Ø¨Ø· Ø§Ù„Ø¨ÙŠØ¦Ø©

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
DRAFT_FILE = DATA_DIR / "alerts_draft.json"

DEFAULT_KIND = "app_update"
DEFAULT_LANG_MODE = "auto"   # auto | en | ar


def _active_load() -> list[dict]:
    try:
        raw = ACTIVE_FILE.read_text("utf-8")
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _active_save(lst: list[dict]) -> None:
    tmp = ACTIVE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ACTIVE_FILE)

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def _L(uid: int) -> str:
    return get_user_lang(uid) or "ar"

def _load_draft() -> dict:
    d = _load_json(DRAFT_FILE) or {}
    d.setdefault("en", ""); d.setdefault("ar", "")
    d.setdefault("lang_mode", DEFAULT_LANG_MODE)
    d.setdefault("kind", DEFAULT_KIND)
    d.setdefault("await", "")
    d.setdefault("ttl", 0)

    # Ù…ÙØ§ØªÙŠØ Ø§Ø®ØªÙŠØ§Ø±ÙŠØ© Ù„Ù„Ù†Ø¸Ø§Ù… Ø§Ù„Ø°ÙƒÙŠ
    d.setdefault("ping_ttl", 0)            # Ù…Ø¯Ø© Ø¸Ù‡ÙˆØ± Ø§Ù„Ù€ ping (Ø«ÙˆØ§Ù†Ù)
    d.setdefault("active_for", 7*24*3600)  # Ù…Ø¯Ø© Ø¨Ù‚Ø§Ø¡ Ø§Ù„ØªÙ†Ø¨ÙŠÙ‡ ÙÙŠ Ø§Ù„ØµÙ†Ø¯ÙˆÙ‚
    d.setdefault("dedupe_key", "")         # Ù…ÙØªØ§Ø Ù…Ù†Ø¹ Ø§Ù„ØªÙƒØ±Ø§Ø±
    return d

def _save_draft(d: dict) -> None:
    _save_json(DRAFT_FILE, d)

async def _safe_edit_text(target: CallbackQuery | Message, text: str, kb: InlineKeyboardBuilder | None = None):
    msg = target.message if isinstance(target, CallbackQuery) else target
    try:
        if kb:
            await msg.edit_text(text, reply_markup=kb.as_markup())
        else:
            await msg.edit_text(text, reply_markup=None)
    except TelegramBadRequest as e:
        # Ø¥Ø°Ø§ Ù†ÙØ³ Ø§Ù„Ù†Øµ Ø£Ùˆ Ø±Ø³Ø§Ù„Ø© Ù‚Ø¯ÙŠÙ…Ø©/ÙˆØ³Ø§Ø¦Ø·
        if "message is not modified" in str(e).lower():
            return
        try:
            if isinstance(target, CallbackQuery):
                await msg.edit_reply_markup(None)
            await msg.answer(text, reply_markup=(kb.as_markup() if kb else None))
        except Exception:
            pass

def _menu_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "alerts.menu.edit") or "âœï¸ ØªØ¹Ø¯ÙŠÙ„ Ø§Ù„Ù†Øµ", callback_data="al:edit")
    kb.button(text=t(lang, "alerts.menu.preview") or "ðŸ‘€ Ù…Ø¹Ø§ÙŠÙ†Ø©", callback_data="al:prev")
    kb.button(text=t(lang, "alerts.menu.send_now") or "ðŸ“£ Ø¥Ø±Ø³Ø§Ù„ Ø§Ù„Ø¢Ù†", callback_data="al:send")
    kb.button(text=t(lang, "alerts.menu.schedule") or "â±ï¸ Ø¬Ø¯ÙˆÙ„Ø©", callback_data="al:sch")
    kb.button(text=t(lang, "alerts.menu.quick") or "â³ Ø¬Ø¯ÙˆÙ„Ø© Ø³Ø±ÙŠØ¹Ø©", callback_data="al:schq")
    kb.button(text=t(lang, "alerts.menu.jobs") or "ðŸ—“ï¸ Ø§Ù„Ø¬ÙˆØ¨Ø² Ø§Ù„Ù…Ø¬Ø¯ÙˆÙ„Ø©", callback_data="al:jobs")
    kb.button(text=t(lang, "alerts.menu.kind") or "ðŸ“‚ Ø§Ù„Ù†ÙˆØ¹", callback_data="al:kind")
    kb.button(text=t(lang, "alerts.menu.lang") or "ðŸŒ ÙˆØ¶Ø¹ Ø§Ù„Ù„ØºØ©", callback_data="al:lang")
    kb.button(text=t(lang, "alerts.menu.active") or "ðŸ“¥ Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª Ø§Ù„Ù†Ø´Ø·Ø©", callback_data="al:active")  # <â€” Ù‡Ø°Ø§ Ø§Ù„Ø³Ø·Ø±
    kb.button(text=t(lang, "alerts.menu.settings") or "âš™ï¸ Ø§Ù„Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª", callback_data="al:cfg")
    kb.button(text=t(lang, "alerts.menu.delete") or "ðŸ—‘ï¸ ØØ°Ù Ø§Ù„Ù…Ø³ÙˆØ¯Ø©", callback_data="al:del")
    kb.button(text=t(lang, "alerts.menu.stats") or "ðŸ“Š Ø¥ØØµØ§Ø¦ÙŠØ§Øª", callback_data="al:stats")
    kb.adjust(2,2,2,2,2,2)
    return kb.as_markup()



# ====================== FSM ======================
class AlStates(StatesGroup):
    wait_en  = State()
    wait_ar  = State()
    wait_ttl = State()
    wait_rate  = State()
    wait_quiet = State()
    wait_maxw  = State()
    wait_actd  = State()

@router.callback_query(F.data == "al:active")
async def al_active(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)

    lang = _L(cb.from_user.id)
    items = _active_load()
    now = int(time.time())

    # ØªÙ†Ø¸ÙŠÙ Ø§Ù„Ù…Ù†ØªÙ‡ÙŠØ© (expires < now) Ø«Ù… ØÙØ¸
    live = []
    for a in items:
        exp = int(a.get("expires") or 0)
        if exp and exp <= now:
            continue
        live.append(a)
    if len(live) != len(items):
        _active_save(live)
    items = live

    if not items:
        kb = InlineKeyboardBuilder()
        kb.button(text=t(lang, "alerts.back") or "Ø±Ø¬ÙˆØ¹", callback_data="al:back")
        await _safe_edit_text(cb, t(lang, "alerts.active.empty") or "Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª â€” 0\nØ§Ø®ØªØ± Ù…Ø¹Ø§ÙŠÙ†Ø© Ø£Ùˆ ØØ°Ù Ù„Ø¥Ø´Ø¹Ø§Ø± Ù…ØØ¯Ø¯.", kb)
        return await cb.answer()

    # Ø¹Ø±Ø¶ Ù…Ø®ØªØµØ± Ù…Ø¹ Ø£Ø²Ø±Ø§Ø± Ù„ÙƒÙ„ Ø¹Ù†ØµØ±
    lines = [t(lang, "alerts.active.header") or "Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª Ø§Ù„Ù†Ø´Ø·Ø©:"]
    kb = InlineKeyboardBuilder()
    for a in sorted(items, key=lambda x: int(x.get("ts", now)), reverse=True):
        aid = str(a.get("id"))
        kind = a.get("kind", "app_update")
        ts = int(a.get("ts", now))
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        lines.append(f"â€¢ {aid}  ({kind})  {when}")
        kb.button(text="ðŸ‘€", callback_data=f"al:a:prev:{aid}")
        kb.button(text="ðŸ—‘ï¸", callback_data=f"al:a:del:{aid}")
    kb.button(text=t(lang, "alerts.active.clear_all") or "ðŸ§¹ ØØ°Ù Ø§Ù„ÙƒÙ„", callback_data="al:a:clear")
    kb.button(text=t(lang, "alerts.back") or "Ø±Ø¬ÙˆØ¹", callback_data="al:back")
    kb.adjust(2,1,1)

    await _safe_edit_text(cb, "\n".join(lines), kb)
    await cb.answer()

@router.callback_query(F.data.regexp(r"^al:a:prev:.+"))
async def al_active_prev(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    aid = cb.data.split(":", 3)[-1]
    items = _active_load()
    it = next((x for x in items if str(x.get("id")) == aid), None)
    if not it:
        await cb.answer("ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯/Ù…Ù†ØªÙ‡ÙŠ", show_alert=True)
        return await al_active(cb)
    # Ø§Ø¹Ø±Ø¶ Ù†Øµ Ø§Ù„Ø¹Ø±Ø¨ÙŠØ©/Ø§Ù„Ø¥Ù†Ø¬Ù„ÙŠØ²ÙŠØ© Ø§Ù„Ù…ØªØ§ØØ©
    body = it.get("text_ar") or it.get("text_en") or "-"
    await cb.message.answer(f"ðŸ”” {aid}\n\n{body}")
    await cb.answer()

@router.callback_query(F.data.regexp(r"^al:a:del:.+"))
async def al_active_del(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    aid = cb.data.split(":", 3)[-1]
    items = _active_load()
    new = [x for x in items if str(x.get("id")) != aid]
    _active_save(new)
    await cb.answer("ØªÙ… Ø§Ù„ØØ°Ù âœ…", show_alert=True)
    await al_active(cb)

@router.callback_query(F.data == "al:a:clear")
async def al_active_clear(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    _active_save([])
    await cb.answer("ØªÙ… ØØ°Ù Ø§Ù„ÙƒÙ„ âœ…", show_alert=True)
    await al_active(cb)


# ====================== ÙØªØ Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© ======================
@router.message(Command("push_update", "push_preview", "push_schedule", "push_stats", "push"))
async def open_menu(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = _L(msg.from_user.id)
    await msg.reply(
        t(lang, "alerts.menu.title") or "Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª ðŸ””\nØªØÙƒÙ… ÙƒØ§Ù…Ù„: ØªØ¹Ø¯ÙŠÙ„/Ù…Ø¹Ø§ÙŠÙ†Ø©/Ø¥Ø±Ø³Ø§Ù„/Ø¬Ø¯ÙˆÙ„Ø©/Ø¥Ù„ØºØ§Ø¡/Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª.",
        reply_markup=_menu_kb(lang),
    )

# ====================== ØªØØ±ÙŠØ± Ø§Ù„Ù†Øµ ======================
def _make_token() -> str:
    return f"AL-{int(time.time())}-{secrets.token_hex(3)}"

@router.callback_query(F.data == "al:edit")
async def al_edit(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)

    lang = _L(cb.from_user.id)
    d = _load_draft(); d["await"] = "en"; _save_draft(d)

    tok = _make_token()
    await state.set_state(AlStates.wait_en)
    await state.update_data(tok=tok, ts=int(time.time()))

    prompt = (t(lang, "alerts.enter_text") or "Ø£Ø±Ø³Ù„ Ù†Øµ Ø§Ù„Ø¥Ø´Ø¹Ø§Ø± (EN Ø£ÙˆÙ„Ù‹Ø§ Ø«Ù… AR).") + \
             f"\n\nâ€” kind: {d.get('kind')}\nâ€” lang_mode: {d.get('lang_mode')}\n\nSend as: EN\nThen send as: AR\n\n[token:{tok}]"
    await cb.message.answer(prompt, reply_markup=ForceReply(selective=True))
    await cb.answer()

@router.message(AlStates.wait_en, F.from_user.func(lambda u: u.id in ADMIN_IDS))
async def capture_text_en(msg: Message, state: FSMContext):
    data = await state.get_data()
    tok = data.get("tok")
    ok_reply = bool(msg.reply_to_message and tok and tok in (msg.reply_to_message.text or ""))
    if not ok_reply:
        return

    txt = (msg.text or "").strip()
    if not txt or txt.startswith("/"):
        return

    d = _load_draft()
    d["en"] = txt
    d["await"] = "ar"
    _save_draft(d)

    tok2 = _make_token()
    await state.set_state(AlStates.wait_ar)
    await state.update_data(tok=tok2, ts=int(time.time()))

    await msg.reply("ØªÙ… Ø§Ù„ØÙØ¸ [EN] â€” Ø£Ø±Ø³Ù„ Ø§Ù„Ø¹Ø±Ø¨ÙŠØ© Ø§Ù„Ø¢Ù†\n[token:{}]".format(tok2),
                    reply_markup=ForceReply(selective=True))

@router.message(AlStates.wait_ar, F.from_user.func(lambda u: u.id in ADMIN_IDS))
async def capture_text_ar(msg: Message, state: FSMContext):
    data = await state.get_data()
    tok = data.get("tok")
    ok_reply = bool(msg.reply_to_message and tok and tok in (msg.reply_to_message.text or ""))
    if not ok_reply:
        return

    txt = (msg.text or "").strip()
    if not txt or txt.startswith("/"):
        return

    d = _load_draft()
    d["ar"] = txt
    d["await"] = ""
    _save_draft(d)

    await state.clear()
    await msg.reply("ØªÙ… Ø§Ù„ØÙØ¸ [AR] âœ…")

# ====================== Ù…Ø¹Ø§ÙŠÙ†Ø© ======================
@router.callback_query(F.data == "al:prev")
async def al_prev(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    lang = _L(cb.from_user.id); d = _load_draft()
    if not (d.get("en") or d.get("ar")):
        return await cb.answer(t(lang, "alerts.no_draft") or "Ù„Ø§ ØªÙˆØ¬Ø¯ Ù…Ø³ÙˆØ¯Ø©.", show_alert=True)
    txt = (t(lang, "alerts.preview.header") or "Ù…Ø¹Ø§ÙŠÙ†Ø© ðŸ‘€") + \
          f"\n\n[EN]\n{d.get('en') or '-'}\n\n[AR]\n{d.get('ar') or '-'}" + \
          f"\n\n(kind={d.get('kind')}, lang_mode={d.get('lang_mode')})"
    await _safe_edit_text(cb, txt); await cb.answer()

# ====================== Ø¥Ø±Ø³Ø§Ù„ Ø§Ù„Ø¢Ù† (TTL) ======================
@router.callback_query(F.data == "al:send")
async def al_send(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    lang = _L(cb.from_user.id); d = _load_draft()
    if not (d.get("en") or d.get("ar")):
        return await cb.answer(t(lang, "alerts.no_draft") or "Ù„Ø§ ØªÙˆØ¬Ø¯ Ù…Ø³ÙˆØ¯Ø©.", show_alert=True)

    await state.set_state(AlStates.wait_ttl)
    d["await"] = ""
    _save_draft(d)
    await _safe_edit_text(cb, t(lang, "alerts.ask_ttl") or "Ø£Ø¯Ø®Ù„ Ù…Ø¯Ø© Ø¨Ù‚Ø§Ø¡ Ø§Ù„Ø±Ø³Ø§Ù„Ø© Ø¨Ø§Ù„Ø«ÙˆØ§Ù†ÙŠ (0 ÙŠØ¹Ù†ÙŠ Ù„Ø§ ØØ°Ù)ØŒ Ù…Ø«Ø§Ù„: 60")
    await cb.answer()

@router.message(AlStates.wait_ttl, F.text.regexp(r"^\d{1,5}$") & F.from_user.func(lambda u: u.id in ADMIN_IDS))
async def handle_ttl_send_now(msg: Message, state: FSMContext):
    lang = _L(msg.from_user.id)
    ttl = int((msg.text or "0").strip())
    if ttl < 0 or ttl > 86400:
        return await msg.reply(t(lang, "alerts.invalid_seconds") or "Ù‚ÙŠÙ…Ø© ØºÙŠØ± ØµØ§Ù„ØØ©. Ø§Ø®ØªØ± Ø¨ÙŠÙ† 0 Ùˆ 86400.")

    d = _load_draft()

    # Ø§Ø®ØªÙŠØ§Ø± Ø§Ù„Ù„ØºØ© ØØ³Ø¨ ÙˆØ¶Ø¹ Ø§Ù„Ù…Ø³ÙˆØ¯Ø©
    en = d.get("en") if d.get("lang_mode") in ("auto", "en") else None
    ar = d.get("ar") if d.get("lang_mode") in ("auto", "ar") else None

    # Ù…ÙØ§ØªÙŠØ Ø°ÙƒÙŠØ©
    kind       = str(d.get("kind") or "app_update")
    ping_ttl   = int(d.get("ping_ttl") or ttl)                 # Ù…Ø¯Ø© Ø§Ù„Ù€ ping
    active_for = int(d.get("active_for") or (7*24*3600))       # Ù…Ø¯Ø© Ø¨Ù‚Ø§Ø¡Ù‡ ÙÙŠ Ø§Ù„ØµÙ†Ø¯ÙˆÙ‚
    dedupe_key = (d.get("dedupe_key") or f"{kind}-{datetime.date.today().isoformat()}")

    # lifetime Ø§Ù„Ø§ÙØªØ±Ø§Ø¶ÙŠ Ø¹Ù†Ø¯ 0
    lifetime = ttl if ttl > 0 else 7*24*3600

    # Ø§Ù„Ø¥Ø±Ø³Ø§Ù„
    sent, skipped, failed = await broadcast(
       msg.bot,
       text_en=en,
       text_ar=ar,
       kind=kind,
       # Ù…Ù‡Ù…:
       delivery="push",          # Ø§Ø¬Ø¹Ù„Ù‡Ø§ push
       smart_target=False,       # Ù„Ø§ Ù†Ø±ÙŠØ¯ Ø§Ø®ØªÙŠØ§Ø± Ø°ÙƒÙŠ Ø§Ù„Ø¢Ù†
       force_push=True,          # â† Ø£Ø±Ø³Ù„ ÙÙˆØ±ÙŠÙ‹Ø§
       ignore_quiet=True,        # â† ØªØ¬Ø§Ù‡Ù„ Ø³Ø§Ø¹Ø§Øª Ø§Ù„Ù‡Ø¯ÙˆØ¡
       # Ø§Ù„Ø¨Ø§Ù‚ÙŠ ÙƒÙ…Ø§ Ù‡Ùˆ:
       ping_ttl=ping_ttl,
       active_for=lifetime,
       target_segment="all",
       dedupe_key=dedupe_key,
       dedupe_window=14*24*3600,
       retry_on_fail=1,
       jitter_ms=250,
    )


    d["ttl"] = ttl; _save_draft(d)
    await state.clear()
    await msg.reply(
        (t(lang, "alerts.sent") or "ØªÙ… Ø§Ù„Ø¥Ø±Ø³Ø§Ù„ âœ…") +
        f"\nsent={sent}, skipped={skipped}, failed={failed}"
    )

# ====================== Ø¬Ø¯ÙˆÙ„Ø© ======================
@router.callback_query(F.data == "al:sch")
async def al_sch(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.clear()
    lang = _L(cb.from_user.id)
    await _safe_edit_text(cb, (t(lang, "alerts.ask_when") or "Ø£Ø¯Ø®Ù„ ÙˆÙ‚Øª Ø§Ù„Ø¬Ø¯ÙˆÙ„Ø© (YYYY-MM-DD HH:MM)") + "\nä¾‹: 2025-08-26 21:30")
    await cb.answer()

@router.message(F.text.regexp(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$") & F.from_user.func(lambda u: u.id in ADMIN_IDS))
async def handle_schedule(msg: Message):
    lang = _L(msg.from_user.id); d = _load_draft()
    if not (d.get("en") or d.get("ar")):
        return await msg.reply(t(lang, "alerts.no_draft") or "Ù„Ø§ ØªÙˆØ¬Ø¯ Ù…Ø³ÙˆØ¯Ø©.")
    try:
        dt = datetime.datetime.strptime(msg.text.strip(), "%Y-%m-%d %H:%M")
        ts = int(dt.timestamp())
    except Exception:
        return await msg.reply(t(lang, "alerts.invalid_time") or "ØµÙŠØºØ© Ø§Ù„ÙˆÙ‚Øª ØºÙŠØ± ØµØÙŠØØ©.")
    en = d.get("en") if d.get("lang_mode") in ("auto", "en") else None
    ar = d.get("ar") if d.get("lang_mode") in ("auto", "ar") else None
    enqueue_job(ts, d.get("kind", "app_update"), en, ar)
    await msg.reply(t(lang, "alerts.scheduled") or "ØªÙ…Øª Ø§Ù„Ø¬Ø¯ÙˆÙ„Ø© âœ…")

@router.callback_query(F.data == "al:schq")
async def al_schq(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.clear()
    lang = _L(cb.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "alerts.quick.15m") or "Ø¨Ø¹Ø¯ 15 Ø¯Ù‚ÙŠÙ‚Ø©", callback_data="al:q:15m")
    kb.button(text=t(lang, "alerts.quick.1h")  or "بعد ساعة",     callback_data="al:q:1h")
    kb.button(text=t(lang, "alerts.quick.24h") or "بعد 24 ساعة",  callback_data="al:q:24h")
    kb.button(text=t(lang, "alerts.back") or "Ø±Ø¬ÙˆØ¹", callback_data="al:back")
    kb.adjust(3,1)
    await _safe_edit_text(cb, t(lang, "alerts.schedule.quick") or "Ø§Ø®ØªØ± Ù…Ø¯Ø© Ø§Ù„Ø¬Ø¯ÙˆÙ„Ø© Ø§Ù„Ø³Ø±ÙŠØ¹Ø©:", kb)
    await cb.answer()

@router.callback_query(F.data.regexp(r"^al:q:(15m|1h|24h)$"))
async def al_quick(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    lang = _L(cb.from_user.id); d = _load_draft()
    if not (d.get("en") or d.get("ar")):
        return await cb.answer(t(lang, "alerts.no_draft") or "Ù„Ø§ ØªÙˆØ¬Ø¯ Ù…Ø³ÙˆØ¯Ø©.", show_alert=True)
    delta = {"15m": 900, "1h": 3600, "24h": 86400}[cb.data.split(":")[-1]]
    ts = int(time.time()) + delta
    en = d.get("en") if d.get("lang_mode") in ("auto", "en") else None
    ar = d.get("ar") if d.get("lang_mode") in ("auto", "ar") else None
    enqueue_job(ts, d.get("kind", "app_update"), en, ar)
    await cb.answer(t(lang, "alerts.scheduled") or "ØªÙ…Øª Ø§Ù„Ø¬Ø¯ÙˆÙ„Ø© âœ…", show_alert=True)

# ====================== Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ø¬ÙˆØ¨Ø² ======================
@router.callback_query(F.data == "al:jobs")
async def al_jobs(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.clear()
    lang = _L(cb.from_user.id)
    jobs = list_jobs()
    if not jobs:
        kb = InlineKeyboardBuilder(); kb.button(text=t(lang, "alerts.back") or "Ø±Ø¬ÙˆØ¹", callback_data="al:back")
        await _safe_edit_text(cb, t(lang, "alerts.jobs.empty") or "Ù„Ø§ ØªÙˆØ¬Ø¯ Ù…Ù‡Ø§Ù… Ù…Ø¬Ø¯ÙˆÙ„Ø©.", kb)
        return await cb.answer()
    lines = [t(lang, "alerts.jobs.header") or "Ø§Ù„Ù…Ù‡Ø§Ù… Ø§Ù„Ù…Ø¬Ø¯ÙˆÙ„Ø©:"]
    kb = InlineKeyboardBuilder()
    for j in sorted(jobs, key=lambda x: int(x.get("ts", 0))):
        ts = int(j.get("ts", 0))
        when = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        jid = j.get("id")
        lines.append(f"â€¢ {when}  ({j.get('kind')})  id={jid}")
        kb.button(text=t(lang, "alerts.jobs.cancel_one") or "Ø¥Ù„ØºØ§Ø¡", callback_data=f"al:cancel:{jid}")
    kb.button(text=t(lang, "alerts.jobs.cancel_all") or "Ø¥Ù„ØºØ§Ø¡ Ø§Ù„ÙƒÙ„", callback_data="al:cancel_all")
    kb.button(text=t(lang, "alerts.back") or "Ø±Ø¬ÙˆØ¹", callback_data="al:back")
    kb.adjust(1,1,1)
    await _safe_edit_text(cb, "\n".join(lines), kb); await cb.answer()

@router.callback_query(F.data.regexp(r"^al:cancel:.+"))
async def al_jobs_cancel(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    jid = cb.data.split(":", 2)[-1]
    ok = cancel_job(jid)
    await cb.answer("ØªÙ… Ø§Ù„Ø¥Ù„ØºØ§Ø¡" if ok else "ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯", show_alert=True)
    await al_jobs(cb, state)

@router.callback_query(F.data == "al:cancel_all")
async def al_jobs_cancel_all(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    n = cancel_all_jobs()
    await cb.answer(f"ØªÙ… Ø¥Ù„ØºØ§Ø¡ {n}", show_alert=True)
    await al_jobs(cb, state)

# ====================== Ø§Ù„Ù†ÙˆØ¹ ÙˆØ§Ù„Ù„ØºØ© ======================
@router.callback_query(F.data == "al:kind")
async def al_kind(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.clear()
    lang = _L(cb.from_user.id); d = _load_draft()
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "alerts.type.app_update") or "ØªØØ¯ÙŠØ« Ø§Ù„ØªØ·Ø¨ÙŠÙ‚", callback_data="al:k:app_update")
    kb.button(text=t(lang, "alerts.type.maintenance") or "ØµÙŠØ§Ù†Ø©", callback_data="al:k:maintenance")
    kb.button(text=t(lang, "alerts.back") or "Ø±Ø¬ÙˆØ¹", callback_data="al:back")
    kb.adjust(2,1)
    await _safe_edit_text(cb, f"{t(lang, 'alerts.set_type') or 'Ø§Ø®ØªØ± Ø§Ù„Ù†ÙˆØ¹'} (cur={d.get('kind')})", kb)
    await cb.answer()

@router.callback_query(F.data.regexp(r"^al:k:(app_update|maintenance)$"))
async def al_kind_set(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    d = _load_draft(); d["kind"] = cb.data.split(":")[-1]; _save_draft(d)
    await cb.answer("OK")
    await al_kind(cb, state)

@router.callback_query(F.data == "al:lang")
async def al_lang(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.clear()
    lang = _L(cb.from_user.id); d = _load_draft()
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "alerts.lang.auto") or "ØØ³Ø¨ Ù„ØºØ© ÙƒÙ„ Ù…Ø³ØªØ®Ø¯Ù…", callback_data="al:l:auto")
    kb.button(text=t(lang, "alerts.lang.en")   or "Ø¥Ø¬Ø¨Ø§Ø± Ø¥Ù†Ø¬Ù„ÙŠØ²ÙŠ",   callback_data="al:l:en")
    kb.button(text=t(lang, "alerts.lang.ar")   or "Ø¥Ø¬Ø¨Ø§Ø± Ø¹Ø±Ø¨ÙŠ",      callback_data="al:l:ar")
    kb.button(text=t(lang, "alerts.back") or "Ø±Ø¬ÙˆØ¹", callback_data="al:back")
    kb.adjust(3,1)
    await _safe_edit_text(cb, f"{t(lang, 'alerts.set_lang') or 'Ø§Ø®ØªØ± Ø§Ù„Ù„ØºØ©'} (cur={d.get('lang_mode')})", kb)
    await cb.answer()

@router.callback_query(F.data.regexp(r"^al:l:(auto|en|ar)$"))
async def al_lang_set(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    d = _load_draft()
    new_mode = cb.data.split(":")[-1]
    if new_mode == d.get("lang_mode"):
        return await cb.answer("Ù†ÙØ³ Ø§Ù„Ø¥Ø¹Ø¯Ø§Ø¯ âœ…", show_alert=False)
    d["lang_mode"] = new_mode; _save_draft(d)
    await cb.answer("OK")
    await al_lang(cb, state)

# ====================== Ø§Ù„Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª ======================
# Ø¯Ø§Ø®Ù„ admin/alerts_admin.py

from utils.alerts_config import get_config, set_config

@router.callback_query(F.data == "al:cfg")
async def al_cfg(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        return await cb.answer("no", show_alert=True)
    await state.clear()
    lang = _L(cb.from_user.id); cfg = get_config()

    body = [
        (t(lang, "alerts.settings.header") or "Ø¥Ø¹Ø¯Ø§Ø¯Ø§Øª Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª:"),
        f"enabled = {cfg.get('enabled')}",
        f"rate_limit = {cfg.get('rate_limit')} msg/s",
        f"quiet_enabled = {cfg.get('quiet_enabled')}",
        f"quiet_hours = {cfg.get('quiet_hours')}",
        f"max_per_week = {cfg.get('max_per_week')}",
        f"active_days = {cfg.get('active_days')}",
        f"tz = {cfg.get('tz')}",
    ]

    kb = InlineKeyboardBuilder()
    kb.button(text=("ðŸ”´ OFF" if not cfg.get("enabled") else "ðŸŸ¢ ON"), callback_data="al:cfg:toggle")
    kb.button(text=("ðŸ”• Quiet: OFF" if not cfg.get("quiet_enabled") else "ðŸ”” Quiet: ON"),
              callback_data="al:cfg:qtoggle")
    kb.button(text=t(lang, "alerts.settings.quiet_hours") or "Ø³Ø§Ø¹Ø§Øª Ø§Ù„Ù‡Ø¯ÙˆØ¡", callback_data="al:cfg:quiet")
    kb.button(text=t(lang, "alerts.settings.rate_limit") or "ØªØØ¯ÙŠØ¯ Ø§Ù„Ø³Ø±Ø¹Ø©", callback_data="al:cfg:rate")
    kb.button(text=t(lang, "alerts.settings.max_per_week") or "Ø§Ù„ØØ¯/Ø£Ø³Ø¨ÙˆØ¹", callback_data="al:cfg:maxw")
    kb.button(text=t(lang, "alerts.settings.active_days") or "Ù†Ø´ÙØ· Ø®Ù„Ø§Ù„ X ÙŠÙˆÙ…", callback_data="al:cfg:actd")
    kb.button(text=t(lang, "alerts.back") or "Ø±Ø¬ÙˆØ¹", callback_data="al:back")
    kb.adjust(2,2,2,1)
    await _safe_edit_text(cb, "\n".join(body), kb); await cb.answer()

@router.callback_query(F.data == "al:cfg:qtoggle")
async def al_cfg_qtoggle(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        return await cb.answer("no", show_alert=True)
    cur = get_config()
    set_config({"quiet_enabled": not bool(cur.get("quiet_enabled"))})
    await cb.answer("OK")
    await al_cfg(cb, state)

@router.callback_query(F.data == "al:cfg:quiet")
async def al_cfg_quiet(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        return await cb.answer("no", show_alert=True)
    await state.set_state(AlStates.wait_quiet)
    lang = _L(cb.from_user.id)
    txt = (t(lang, "alerts.settings.ask_quiet_hours") or
          "Ø£Ø¯Ø®Ù„ Ø³Ø§Ø¹Ø§Øª Ø§Ù„Ù‡Ø¯ÙˆØ¡ hh:mm-hh:mm (Ù…Ø«Ø§Ù„ 22:00-08:00)\n"
          "Ø§ÙƒØªØ¨ off Ù„Ø¥ÙŠÙ‚Ø§Ù Ø§Ù„Ù‡Ø¯ÙˆØ¡ ÙƒÙ„ÙŠÙ‹Ø§.")
    await _safe_edit_text(cb, txt); await cb.answer()

@router.message(AlStates.wait_quiet, F.from_user.func(lambda u: u.id in ADMIN_IDS))
async def al_cfg_quiet_set(msg: Message, state: FSMContext):
    lang = _L(msg.from_user.id)
    val = (msg.text or "").strip()
    if val.lower() in {"off", "none", ""}:
        set_config({"quiet_enabled": False})
        await state.clear()
        return await msg.reply(t(lang, "alerts.settings.saved") or "ØªÙ… Ø§Ù„ØÙØ¸ âœ…")
    # ØªØÙ‚Ù‚ Ø¨Ø³ÙŠØ· Ù„Ù„ØµÙŠØºØ©
    import re
    if not re.fullmatch(r"\d{2}:\d{2}-\d{2}:\d{2}", val):
        return await msg.reply("ØµÙŠØºØ© ØºÙŠØ± ØµØÙŠØØ©. Ù…Ø«Ø§Ù„: 22:00-08:00 Ø£Ùˆ off")
    set_config({"quiet_enabled": True, "quiet_hours": val})
    await state.clear()
    await msg.reply(t(lang, "alerts.settings.saved") or "ØªÙ… Ø§Ù„ØÙØ¸ âœ…")


@router.callback_query(F.data == "al:cfg:toggle")
async def al_cfg_toggle(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    cfg = get_config(); set_config({"enabled": not bool(cfg.get("enabled"))})
    await cb.answer("OK")
    await al_cfg(cb, state)

@router.callback_query(F.data == "al:cfg:rate")
async def al_cfg_rate(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.set_state(AlStates.wait_rate)
    lang = _L(cb.from_user.id)
    await _safe_edit_text(cb, t(lang, "alerts.settings.ask_rate_limit") or "Ø£Ø±Ø³Ù„ Ø§Ù„Ø³Ø±Ø¹Ø© (Ø±Ø³Ø§Ø¦Ù„/Ø«Ø§Ù†ÙŠØ©): 1..1000")
    await cb.answer()

@router.message(AlStates.wait_rate, F.text.regexp(r"^\d{1,4}$") & F.from_user.func(lambda u: u.id in ADMIN_IDS))
async def al_cfg_rate_set(msg: Message, state: FSMContext):
    lang = _L(msg.from_user.id)
    set_config({"rate_limit": int(msg.text)})
    await state.clear()
    await msg.reply(t(lang, "alerts.settings.saved") or "ØªÙ… Ø§Ù„ØÙØ¸ âœ…")

@router.callback_query(F.data == "al:cfg:quiet")
async def al_cfg_quiet(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.set_state(AlStates.wait_quiet)
    lang = _L(cb.from_user.id)
    await _safe_edit_text(cb, (t(lang, "alerts.settings.ask_quiet_hours") or "Ø£Ø¯Ø®Ù„ Ø³Ø§Ø¹Ø§Øª Ø§Ù„Ù‡Ø¯ÙˆØ¡ hh:mm-hh:mm") + "\nä¾‹: 22:00-08:00")
    await cb.answer()

@router.message(AlStates.wait_quiet, F.text.regexp(r"^\d{2}:\d{2}-\d{2}:\d{2}$") & F.from_user.func(lambda u: u.id in ADMIN_IDS))
async def al_cfg_quiet_set(msg: Message, state: FSMContext):
    lang = _L(msg.from_user.id)
    set_config({"quiet_hours": msg.text.strip()})
    await state.clear()
    await msg.reply(t(lang, "alerts.settings.saved") or "ØªÙ… Ø§Ù„ØÙØ¸ âœ…")

@router.callback_query(F.data == "al:cfg:maxw")
async def al_cfg_maxw(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.set_state(AlStates.wait_maxw)
    lang = _L(cb.from_user.id)
    await _safe_edit_text(cb, t(lang, "alerts.settings.ask_max_per_week") or "Ø£Ø±Ø³Ù„ Ø§Ù„ØØ¯ Ø§Ù„Ø£Ù‚ØµÙ‰ ÙÙŠ Ø§Ù„Ø£Ø³Ø¨ÙˆØ¹:")
    await cb.answer()

@router.message(AlStates.wait_maxw, F.text.regexp(r"^\d{1,3}$") & F.from_user.func(lambda u: u.id in ADMIN_IDS))
async def al_cfg_maxw_set(msg: Message, state: FSMContext):
    lang = _L(msg.from_user.id)
    set_config({"max_per_week": int(msg.text)})
    await state.clear()
    await msg.reply(t(lang, "alerts.settings.saved") or "ØªÙ… Ø§Ù„ØÙØ¸ âœ…")

@router.callback_query(F.data == "al:cfg:actd")
async def al_cfg_actd(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.set_state(AlStates.wait_actd)
    lang = _L(cb.from_user.id)
    await _safe_edit_text(cb, t(lang, "alerts.settings.ask_active_days") or "Ø£Ø±Ø³Ù„ Ø¹Ø¯Ø¯ Ø§Ù„Ø£ÙŠØ§Ù… Ø§Ù„Ù†Ø´Ø·Ø© (Ø§Ø³ØªÙ‡Ø¯Ø§Ù Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…ÙŠÙ† Ø®Ù„Ø§Ù„ X ÙŠÙˆÙ…):")
    await cb.answer()

@router.message(AlStates.wait_actd, F.text.regexp(r"^\d{1,4}$") & F.from_user.func(lambda u: u.id in ADMIN_IDS))
async def al_cfg_actd_set(msg: Message, state: FSMContext):
    lang = _L(msg.from_user.id)
    set_config({"active_days": int(msg.text)})
    await state.clear()
    await msg.reply(t(lang, "alerts.settings.saved") or "ØªÙ… Ø§Ù„ØÙØ¸ âœ…")

# ====================== Ø§Ù„Ø¥ØØµØ§Ø¦ÙŠØ§Øª / ØØ°Ù / Ø±Ø¬ÙˆØ¹ ======================
@router.callback_query(F.data == "al:stats")
async def al_stats(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    lang = _L(cb.from_user.id)
    stats = _load_json(STATS_FILE) or {}
    wk = max(stats.keys()) if stats else "-"
    body = stats.get(wk, {}) if wk != "-" else {}
    txt = [t(lang, "alerts.stats.header") or "Ø¥ØØµØ§Ø¦ÙŠØ§Øª Ù‡Ø°Ø§ Ø§Ù„Ø£Ø³Ø¨ÙˆØ¹:"]
    if wk != "-":
        txt.append(f"Week {wk}: app_update={body.get('app_update',0)}, maintenance={body.get('maintenance',0)}")
    else:
        txt.append("No data yet")
    await _safe_edit_text(cb, "\n".join(txt)); await cb.answer()

@router.callback_query(F.data == "al:del")
async def al_del(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    _save_draft({
        "en": "", "ar": "", "lang_mode": DEFAULT_LANG_MODE, "kind": DEFAULT_KIND,
        "await": "", "ttl": 0, "ping_ttl": 0, "active_for": 7*24*3600, "dedupe_key": ""
    })
    await state.clear()
    await cb.answer("OK", show_alert=True)

@router.callback_query(F.data == "al:back")
async def al_back(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)
    await state.clear()
    lang = _L(cb.from_user.id)
    # Ø±Ø¬ÙˆØ¹ Ù†Ø¸ÙŠÙ: Ø±Ø³Ø§Ù„Ø© ÙˆØ§ØØ¯Ø© Ù…Ø¹ Ø§Ù„ÙƒÙŠØ¨ÙˆØ±Ø¯
    await _safe_edit_text(cb, t(lang, "alerts.menu.title") or "Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª ðŸ””", None)
    await cb.message.edit_text(
        t(lang, "alerts.menu.title") or "Ø¥Ø¯Ø§Ø±Ø© Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª ðŸ””",
        reply_markup=_menu_kb(lang)
    )
    await cb.answer()

