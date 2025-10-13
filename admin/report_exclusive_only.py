from __future__ import annotations

# admin/report_exclusive_only.py


import logging, html, json, time
from pathlib import Path
from datetime import datetime, timezone

# موديل البلاغات الأصلي
from handlers import report as _report_mod

# فحص كتم التنبيهات + لغة الهدف (اختياري)
try:
    from admin.report_admin import alerts_is_muted  # زر "تنبيهاتي"
except Exception:
    alerts_is_muted = None  # type: ignore

try:
    from lang import get_user_lang, t
except Exception:
    def get_user_lang(_): return "en"
    def t(lang, key): return key

log = logging.getLogger(__name__)

# احتفظ بنسخة من الدالة الأصلية مرة واحدة فقط
if not hasattr(_report_mod, "_notify_admins_new_report__orig"):
    _report_mod._notify_admins_new_report__orig = _report_mod._notify_admins_new_report  # type: ignore[attr-defined]

# ---------- إعدادات/حالة التبريد (نفس أسماء الملفات المستخدمة في report_admin.py) ----------
DATA_DIR       = Path("data")
SETTINGS_FILE  = DATA_DIR / "report_settings.json"   # {"enabled":true,"cooldown_days":3,...}
STATE_FILE     = DATA_DIR / "report_users.json"      # {"last": {"<uid>": "2025-10-11T09:55:53Z"}}

def _load_json(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return json.loads(json.dumps(default))

def _save_json(p: Path, data):
    try:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def _get_settings():
    d = _load_json(SETTINGS_FILE, {"enabled": True, "cooldown_days": 3, "banned": []})
    d.setdefault("enabled", True)
    d.setdefault("cooldown_days", 3)
    return d

def _state_read():  return _load_json(STATE_FILE, {"last": {}})
def _state_write(d): _save_json(STATE_FILE, d)

def _iso_to_ts(s: str) -> float:
    if not s: return 0.0
    try:
        # يدعم …Z و …+00:00
        if s.endswith("Z"): s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0

def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()

# -------------------------------------------------------------------------------------------

async def _notify_admins_new_report_exclusive(m, user_id: int, text: str):
    """
    NEW: قبل تنبيه الأدمن، نطبّق "التبريد".
    - لو المستخدم داخل تبريد -> لا إشعار للأدمن + نبلغ المستخدم برفض البلاغ.
    - وإلا نكمل إرسال التنبيه (حصريًا إلى ADMIN_ALERT_CHAT_ID لو مضبوط).
    """
    # ===== تحقق من التبريد =====
    st  = _get_settings()
    if st.get("enabled", True):
        cd_days = int(st.get("cooldown_days") or 0)
        if cd_days > 0:
            state = _state_read()
            last_map: dict = state.get("last", {}) or {}
            last_iso = str(last_map.get(str(user_id)) or "")
            last_ts  = _iso_to_ts(last_iso)
            now_ts   = _now_ts()
            window   = cd_days * 86400
            if last_ts and (now_ts - last_ts) < window:
                # داخل التبريد: امنع البلاغ فعلاً
                left = int(window - (now_ts - last_ts))
                hours = max(1, left // 3600)
                lang = get_user_lang(user_id) or "en"
                try:
                    await m.answer(
                        "⛔ " + (t(lang, "report.cooldown_active") or "لا يمكنك فتح بلاغ جديد الآن.")
                        + f"\n🕒 "
                        + (t(lang, "report.try_later_in") or "جرّب لاحقًا بعد")
                        + f": ~{hours}h."
                    )
                except Exception:
                    pass
                log.info(f"[report-exclusive] blocked by cooldown: uid={user_id}, left≈{hours}h")
                return
            else:
                # ليس داخل تبريد -> سجّل وقت الاستلام الآن ليصبح التبريد فعّالًا
                last_map[str(user_id)] = _report_mod.utcnow_iso()
                state["last"] = last_map
                _state_write(state)

    # ===== الإرسال الحصري (نفس منطقك السابق) =====
    try:
        target = int(getattr(_report_mod, "ADMIN_ALERT_CHAT_ID", 0) or 0)
    except Exception:
        target = 0

    if target:
        try:
            if target > 0 and callable(alerts_is_muted):
                try:
                    if alerts_is_muted(target):  # type: ignore[misc]
                        return
                except Exception:
                    pass

            full_name = html.escape(getattr(m.from_user, "full_name", "-") or "-")
            username = getattr(m.from_user, "username", None)
            username_txt = f"@{username}" if username else "-"
            safe_text = text
            a_lang = get_user_lang(target) or "en"
            admin_msg = (
                "⚠️ <b>New Report</b>\n"
                f"• ID: <code>{user_id}</code>\n"
                f"• Name: {full_name}\n"
                f"• Username: {username_txt}\n"
                f"• Date: <code>{_report_mod.utcnow_iso()}</code>\n"
                "— — —\n" + safe_text
            )
            kb = _report_mod._admin_controls_kb(user_id, a_lang)

            await m.bot.send_message(
                chat_id=target, text=admin_msg, reply_markup=kb,
                parse_mode="HTML", disable_web_page_preview=True
            )
            try:
                await m.bot.copy_message(
                    chat_id=target, from_chat_id=m.chat.id, message_id=m.message_id
                )
            except Exception as e:
                log.warning(f"[report-exclusive] copy_message -> {target} failed: {e}")

            log.info(f"[report-exclusive] Notified exclusive target {target} about report from {user_id}")
        except Exception as e:
            log.error(f"[report-exclusive] notify target failed: {e}")
        return

    # لا يوجد هدف حصري -> السلوك الأصلي
    try:
        await _report_mod._notify_admins_new_report__orig(m, user_id, text)  # type: ignore[attr-defined]
    except Exception as e:
        log.error(f"[report-exclusive] fallback original notify failed: {e}")

# تطبيق الباتش
_report_mod._notify_admins_new_report = _notify_admins_new_report_exclusive  # type: ignore[assignment]
