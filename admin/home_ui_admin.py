# handlers/home_ui_admin.py
from __future__ import annotations

import json, os
from pathlib import Path
from typing import Tuple

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from lang import t, get_user_lang

router = Router(name="home_ui_admin")

# ============ تخزين ============
DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
CFG_FILE = DATA_DIR / "home_ui_cfg.json"

DEFAULT_CFG = {
    "theme": "neo",
    "density": "comfy",
    "sep": "soft",
    "icons": "modern",
    "bullets": True,
    "tip": True,
    "version": True,
    "users": True,
    "alerts": True,
}

def _load_cfg() -> dict:
    try:
        d = json.loads(CFG_FILE.read_text("utf-8"))
        if isinstance(d, dict):
            out = DEFAULT_CFG.copy(); out.update(d); return out
    except Exception:
        pass
    return DEFAULT_CFG.copy()

def _save_cfg(d: dict) -> None:
    tmp = CFG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(CFG_FILE)

# ============ صلاحيات ============
def _admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
    ids: set[int] = {int(p) for p in str(raw).split(",") if p.strip().isdigit()}
    return ids or {7360982123}

def _is_admin(uid: int) -> bool:
    return uid in _admin_ids()

# ============ ترجمة مساعدة ============
def _T(lang: str, key: str, default: str = "") -> str:
    try:
        s = t(lang, key)
        if isinstance(s, str) and s.strip():
            return s
    except Exception:
        pass
    return default or key

def _norm_lang(uid: int) -> str:
    # نجبر اللغة على ar/en صغيرة
    val = (get_user_lang(uid) or "ar").strip().lower()
    return "ar" if val.startswith("ar") else "en"

def _val_label(lang: str, group: str, value_id: str) -> str:
    return _T(lang, f"homeui.{group}.{value_id}", value_id)

def _onoff(lang: str, flag: bool) -> str:
    return _T(lang, "homeui.status.on", "ON") if flag else _T(lang, "homeui.status.off", "OFF")

async def _safe_edit(target: Message | CallbackQuery, text: str, kb: InlineKeyboardBuilder | None = None):
    msg = target.message if isinstance(target, CallbackQuery) else target
    try:
        await msg.edit_text(text, reply_markup=(kb.as_markup() if kb else None), parse_mode=ParseMode.HTML)
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            raise

# ============ معاينة الواجهة ============
try:
    from handlers.home_hero import render_home_card as _render_home
except Exception:
    _render_home = None

async def _preview_in_chat(msg: Message, lang: str):
    if _render_home:
        try:
            await _render_home(msg, lang=lang); return
        except Exception:
            pass
    await msg.answer(_T(lang, "homeui.preview.fallback", "Preview sent."))

# ============ نص الحالة الآمن ============
def _state_line(lang: str, cfg: dict) -> str:
    # قالب من ملف الترجمة (لو صالح)
    tpl = _T(
        lang, "homeui.state",
        "• theme: {theme}  |  density: {density}  |  sep: {sep}  |  icons: {icons}\n"
        "• Bullets={bullets} Tip={tip} Version={version} Users={users} Alerts={alerts}"
    )
    placeholders = ("{theme}","{density}","{sep}","{icons}","{bullets}","{tip}","{version}","{users}","{alerts}")
    if not all(p in tpl for p in placeholders):
        # fallback مُترجم بالكامل
        if lang == "ar":
            tpl = ("• السِمة: {theme}  |  الكثافة: {density}  |  الفواصل: {sep}  |  الأيقونات: {icons}\n"
                   "• النقاط={bullets} التلميح={tip} الإصدار={version} المستخدمون={users} الإشعارات={alerts}")
        else:
            tpl = ("• theme: {theme}  |  density: {density}  |  sep: {sep}  |  icons: {icons}\n"
                   "• Bullets={bullets} Tip={tip} Version={version} Users={users} Alerts={alerts}")

    return tpl.format(
        theme   = _val_label(lang, "theme",   cfg["theme"]),
        density = _val_label(lang, "density", cfg["density"]),
        sep     = _val_label(lang, "sep",     cfg["sep"]),
        icons   = _val_label(lang, "icons",   cfg["icons"]),
        bullets = _onoff(lang, cfg["bullets"]),
        tip     = _onoff(lang, cfg["tip"]),
        version = _onoff(lang, cfg["version"]),
        users   = _onoff(lang, cfg["users"]),
        alerts  = _onoff(lang, cfg["alerts"]),
    )

def _admin_title(lang: str) -> str:
    return _T(lang, "homeui.admin.title", "Home UI setup")

def _admin_hint(lang: str) -> str:
    return _T(lang, "homeui.admin.hint",
              "Use the buttons below to toggle/change. Preview will send a fresh card in this chat.")

def _main_text(lang: str, cfg: dict) -> str:
    return f"<b>{_admin_title(lang)}</b>\n\n{_state_line(lang, cfg)}\n\n{_admin_hint(lang)}"

def _row(kb: InlineKeyboardBuilder, *btns: InlineKeyboardButton):
    kb.row(*btns)

def _main_kb(lang: str, cfg: dict) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    _row(kb,
         InlineKeyboardButton(text=f"🐍 {_val_label(lang,'theme','neo')}",    callback_data="homeui:theme:neo"),
         InlineKeyboardButton(text=f"{_val_label(lang,'theme','glass')}",     callback_data="homeui:theme:glass"))
    _row(kb,
         InlineKeyboardButton(text=_val_label(lang,'theme','chip'),           callback_data="homeui:theme:chip"),
         InlineKeyboardButton(text=_val_label(lang,'theme','plaque'),         callback_data="homeui:theme:plaque"))
    _row(kb,
         InlineKeyboardButton(text=_val_label(lang,'theme','banner'),         callback_data="homeui:theme:banner"),
         InlineKeyboardButton(text=_val_label(lang,'theme','receipt'),        callback_data="homeui:theme:receipt"))

    _row(kb,
         InlineKeyboardButton(
             text=_T(lang,"homeui.value.density","Density: {name}").format(
                 name=_val_label(lang,"density",cfg["density"])),
             callback_data="homeui:density:open"),
         InlineKeyboardButton(
             text=_T(lang,"homeui.value.sep","Sep: {name}").format(
                 name=_val_label(lang,"sep",cfg["sep"])),
             callback_data="homeui:sep:open"))
    _row(kb,
         InlineKeyboardButton(
             text=_T(lang,"homeui.value.icons","Icons: {name}").format(
                 name=_val_label(lang,"icons",cfg["icons"])),
             callback_data="homeui:icons:open"))

    _row(kb,
         InlineKeyboardButton(text=f"{_T(lang,'homeui.toggle.bullets','Bullets')}  {_onoff(lang,cfg['bullets'])}",
                              callback_data="homeui:toggle:bullets"),
         InlineKeyboardButton(text=f"{_T(lang,'homeui.toggle.tip','Tip')}  {_onoff(lang,cfg['tip'])}",
                              callback_data="homeui:toggle:tip"))
    _row(kb,
         InlineKeyboardButton(text=f"{_T(lang,'homeui.toggle.version','Version')}  {_onoff(lang,cfg['version'])}",
                              callback_data="homeui:toggle:version"),
         InlineKeyboardButton(text=f"{_T(lang,'homeui.toggle.users','Users')}  {_onoff(lang,cfg['users'])}",
                              callback_data="homeui:toggle:users"))
    _row(kb,
         InlineKeyboardButton(text=f"{_T(lang,'homeui.toggle.alerts','Alerts')}  {_onoff(lang,cfg['alerts'])}",
                              callback_data="homeui:toggle:alerts"))

    _row(kb,
         InlineKeyboardButton(text=_T(lang,"homeui.btn.set_density","Set density"), callback_data="homeui:density:open"),
         InlineKeyboardButton(text=_T(lang,"homeui.btn.set_sep","Set sep"),         callback_data="homeui:sep:open"))
    _row(kb,
         InlineKeyboardButton(text=_T(lang,"homeui.btn.set_icons","Set icons"),     callback_data="homeui:icons:open"),
         InlineKeyboardButton(text=_T(lang,"homeui.btn.preview","Preview now"),     callback_data="homeui:preview"))
    _row(kb,
         InlineKeyboardButton(text=_T(lang,"homeui.btn.restore","Restore defaults"), callback_data="homeui:restore"))
    return kb

def _picker_kb(lang: str, group: str, values: Tuple[str, ...]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for v in values:
        row.append(InlineKeyboardButton(text=_val_label(lang, group, v), callback_data=f"homeui:set:{group}:{v}"))
        if len(row) == 2:
            kb.row(*row); row = []
    if row:
        kb.row(*row)
    kb.row(InlineKeyboardButton(text=_T(lang,"homeui.btn.back","Back"), callback_data="homeui:back"))
    return kb

# ============ الأوامر ============
@router.message(Command("home_ui"))
async def open_ui(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = _norm_lang(msg.from_user.id)
    cfg = _load_cfg()
    await msg.answer(_main_text(lang, cfg), reply_markup=_main_kb(lang, cfg).as_markup(), parse_mode=ParseMode.HTML)

# ============ الأزرار ============
@router.callback_query(F.data.startswith("homeui:"))
async def handle_cb(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("no", show_alert=True)

    lang = _norm_lang(cb.from_user.id)
    cfg = _load_cfg()
    parts = cb.data.split(":")

    if parts[1] == "theme":
        cfg["theme"] = parts[2]; _save_cfg(cfg)
        await _safe_edit(cb, _main_text(lang, cfg), _main_kb(lang, cfg))
        return await cb.answer("OK")

    if parts[1] == "toggle":
        key = parts[2]
        if key in cfg and isinstance(cfg[key], bool):
            cfg[key] = not cfg[key]; _save_cfg(cfg)
        await _safe_edit(cb, _main_text(lang, cfg), _main_kb(lang, cfg))
        return await cb.answer("OK")

    if parts[1] == "density" and parts[2] == "open":
        return await _safe_edit(cb, _T(lang,"homeui.pick.density","Choose density:"), _picker_kb(lang,"density",("comfy","compact")))

    if parts[1] == "sep" and parts[2] == "open":
        return await _safe_edit(cb, _T(lang,"homeui.pick.sep","Choose separators style:"), _picker_kb(lang,"sep",("soft","hard")))

    if parts[1] == "icons" and parts[2] == "open":
        return await _safe_edit(cb, _T(lang,"homeui.pick.icons","Choose icon set:"), _picker_kb(lang,"icons",("modern","classic")))

    if parts[1] == "set":
        group, val = parts[2], parts[3]
        if group in ("density","sep","icons"):
            cfg[group] = val; _save_cfg(cfg)
            await _safe_edit(cb, _main_text(lang, cfg), _main_kb(lang, cfg))
            return await cb.answer("OK")

    if parts[1] == "preview":
        await cb.answer(_T(lang,"homeui.preview.sending","Preview…"))
        return await _preview_in_chat(cb.message, lang)

    if parts[1] == "restore":
        _save_cfg(DEFAULT_CFG.copy())
        cfg2 = _load_cfg()
        await _safe_edit(cb, _main_text(lang, cfg2), _main_kb(lang, cfg2))
        return await cb.answer(_T(lang,"homeui.restored","Restored"))

    if parts[1] == "back":
        return await _safe_edit(cb, _main_text(lang, cfg), _main_kb(lang, cfg))

    await cb.answer("OK")
