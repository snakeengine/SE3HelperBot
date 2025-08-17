# admin/admin_hub.py
from __future__ import annotations

import os
import json
from pathlib import Path
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from lang import t, get_user_lang

# (اختياري) معلومات آخر إصدار للتطبيق
try:
    from handlers.app_download import (
        _load_release as app_load_release,
        _caption as app_caption,
        _info_text as app_info_text,
    )
except Exception:
    app_load_release = None
    app_caption = None
    app_info_text = None

# عدد المستخدمين: نستخدم الميدلوير إن وُجد، وإلا fallback ذكي
try:
    from middlewares.user_tracker import get_users_count  # المفضل
except Exception:
    def get_users_count() -> int:
        try:
            p = Path("data") / "users.json"
            if not p.exists():
                return 0
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                u = data.get("users")
                if isinstance(u, dict):
                    return len(u)
                if isinstance(u, list):
                    return len(u)
                return len(data)
            if isinstance(data, list):
                return len(data)
            return 0
        except Exception:
            return 0

router = Router(name="admin_hub")

# ===== أدوات صغيرة =====
def tt(lang: str, key: str, fallback: str) -> str:
    """t() آمنة مع نص بديل إذا المفتاح ناقص."""
    try:
        val = t(lang, key)
        if isinstance(val, str) and val.strip() and val != key:
            return val
    except Exception:
        pass
    return fallback

# قراءة قائمة الأدمن من .env (يدعم ADMIN_IDS أو ADMIN_ID)
_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [7360982123]

def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ===== الكيبورد الرئيسي (2×2) =====
def _kb_main(lang: str) -> InlineKeyboardMarkup:
    ver = ""
    if app_load_release:
        try:
            rel = app_load_release()
            if rel and rel.get("version") and rel["version"] != "-":
                ver = f" ({rel['version']})"
        except Exception:
            ver = ""

    # نصوص الأزرار مع أيقونات
    suppliers_reqs   = "📂 " + tt(lang, "admin_hub_btn_resapps", "طلبات الموردين")
    suppliers_dir    = "📖 " + tt(lang, "admin_hub_btn_supdir", "دليل الموردين")

    app_txt          = "📦 " + tt(lang, "admin_hub_btn_app", "التطبيق (APK)") + ver
    security_txt     = "🛡️ " + tt(lang, "admin_hub_btn_security", "الأمن (الألعاب) • أدمن")

    reports_inbox    = "📥 " + tt(lang, "admin_hub_btn_reports_inbox", "التقارير — الوارد")
    servers_inbox    = "📡 " + tt(lang, "admin_hub_btn_server", "السيرفرات — الوارد")

    reports_settings = "⚙️ " + tt(lang, "admin_hub_btn_reports_settings", "التقارير — الإعدادات")
    users_count      = "👥 " + tt(lang, "admin_hub_btn_users_count", "عدد المستخدمين")

    promoters_txt    = "📣 " + tt(lang, "admin_hub_btn_promoters", "تحكم المروّجين")
    maint_text       = "🛠️ " + tt(lang, "admin_hub_btn_maintenance", "وضع الصيانة")
    vip_admin_txt    = "👑 " + tt(lang, "admin_hub_btn_vip_admin", "إدارة VIP")
    close_txt        = "❌ " + tt(lang, "admin_hub_btn_close", "إغلاق")

    kb = InlineKeyboardBuilder()

    # صف 1
    kb.row(
        InlineKeyboardButton(text=suppliers_reqs, callback_data="ah:resapps"),
        InlineKeyboardButton(text=suppliers_dir,  callback_data="ah:supdir"),
    )
    # صف 2
    kb.row(
        InlineKeyboardButton(text=app_txt,      callback_data="ah:app"),
        InlineKeyboardButton(text=security_txt, callback_data="sec:admin"),
    )
    # صف 3
    kb.row(
        InlineKeyboardButton(text=reports_inbox, callback_data="rin:open"),
        InlineKeyboardButton(text=servers_inbox, callback_data="server_status:admin"),
    )
    # صف 4
    kb.row(
        InlineKeyboardButton(text=reports_settings, callback_data="ra:open"),
        InlineKeyboardButton(text=users_count,      callback_data="ah:users_count"),
    )
    # صف 5 — تحكم المروّجين + وضع الصيانة
    kb.row(
        InlineKeyboardButton(text=promoters_txt, callback_data="promadm:open"),
        InlineKeyboardButton(text=maint_text,     callback_data="maint:status"),
    )
    # صف 6 — إدارة VIP + إغلاق
    kb.row(
        InlineKeyboardButton(text=vip_admin_txt, callback_data="vipadm:menu"),
        InlineKeyboardButton(text=close_txt,     callback_data="ah:close"),
    )

    return kb.as_markup()

# ===== عرض اللوحة عبر أمر /admin =====
@router.message(Command("admin"))
async def admin_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    lang = get_user_lang(msg.from_user.id) or "en"
    title = tt(lang, "admin_hub_title", "لوحة الأدمن ⚡")
    desc  = tt(lang, "admin_hub_choose", "اختر إجراء:")
    await msg.answer(f"<b>{title}</b>\n{desc}",
                     reply_markup=_kb_main(lang),
                     disable_web_page_preview=True,
                     parse_mode=ParseMode.HTML)

# ===== فتح القائمة من زر =====
@router.callback_query(F.data == "ah:menu")
async def ah_menu(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    title = tt(lang, "admin_hub_title", "لوحة الأدمن ⚡")
    desc  = tt(lang, "admin_hub_choose", "اختر إجراء:")
    await cb.message.edit_text(f"<b>{title}</b>\n{desc}",
                               reply_markup=_kb_main(lang),
                               disable_web_page_preview=True,
                               parse_mode=ParseMode.HTML)
    await cb.answer()

# ===== روابط الأقسام الأخرى كما هي (بعضها في وحدات أخرى) =====
@router.callback_query(F.data == "ah:app")
async def open_app_panel(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"

    ver_val = None
    ver_txt = ""
    if app_load_release:
        try:
            rel = app_load_release()
            ver_val = (rel or {}).get("version")
            if ver_val and ver_val != "-":
                ver_txt = f" ({ver_val})"
        except Exception:
            ver_val = None
            ver_txt = ""

    kb = InlineKeyboardBuilder()
    kb.button(text="📤 " + tt(lang, "admin.app.btn_upload", "رفع"), callback_data="adm:app_help")
    kb.button(text="📥 " + tt(lang, "admin.app.btn_send", "إرسال") + ver_txt, callback_data="adm:app_send")
    kb.button(text="ℹ️ " + tt(lang, "admin.app.btn_info", "معلومات"),   callback_data="adm:app_info")
    kb.button(text="🗑️ " + tt(lang, "admin.app.btn_remove", "حذف"), callback_data="adm:app_remove")
    kb.adjust(2)

    title = tt(lang, "admin.app.title", "إدارة التطبيق") + (f" — {ver_val}" if ver_val else "")
    await cb.message.edit_text(title, reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data == "adm:app_help")
async def app_help(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.answer(tt(lang, "admin.app.help", "أرسل ملف APK كـ Document وسيتم حفظه."))
    await cb.answer()

@router.callback_query(F.data == "adm:app_send")
async def app_send(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    if not app_load_release or not app_caption:
        return await cb.answer(tt(lang, "admin_hub_module_missing", "الوحدة غير متاحة"), show_alert=True)
    rel = app_load_release()
    if not rel:
        await cb.answer(tt(lang, "app.no_release_short", "لا يوجد إصدار"), show_alert=True)
        return
    await cb.message.answer_document(document=rel["file_id"], caption=app_caption(lang, rel))
    await cb.answer()

@router.callback_query(F.data == "adm:app_info")
async def app_info(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    if not app_load_release or not app_info_text:
        return await cb.answer(tt(lang, "admin_hub_module_missing", "الوحدة غير متاحة"), show_alert=True)
    rel = app_load_release()
    if not rel:
        await cb.answer(tt(lang, "app.no_release_short", "لا يوجد إصدار"), show_alert=True)
        return
    await cb.message.answer(app_info_text(lang, rel))
    await cb.answer()

@router.callback_query(F.data == "ah:users_count")
async def ah_users_count(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    n = get_users_count()
    try:
        txt = f"👥 {t(lang, 'admin.users_count').format(n=n)}"
    except Exception:
        txt = f"👥 Total users: {n}"
    await cb.message.answer(txt)
    await cb.answer("✅")

@router.callback_query(F.data == "ah:close")
async def ah_close(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        l = get_user_lang(cb.from_user.id) or "en"
        return await cb.answer(tt(l, "admins_only", "للمشرفين فقط"), show_alert=True)
    lang = get_user_lang(cb.from_user.id) or "en"
    await cb.message.edit_text(tt(lang, "admin_closed", "تم الإغلاق"))
    await cb.answer()
