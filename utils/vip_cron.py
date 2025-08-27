# utils/vip_cron.py
from __future__ import annotations
import os, time, asyncio, random, logging
from typing import Dict, Optional, Tuple

from utils.vip_store import list_vips, _now_ts, purge_expired
from lang import t, get_user_lang

logger = logging.getLogger(__name__)

# ========= الإعدادات من .env =========
VIP_TEST_MODE      = os.getenv("VIP_TEST_MODE", "0").strip() not in ("0", "false", "False", "")
VIP_REMIND_ENABLED = os.getenv("VIP_REMIND_ENABLED", "1").strip() not in ("0", "false", "False", "")

if VIP_TEST_MODE:
    VIP_CRON_INTERVAL = max(1, int(os.getenv("VIP_CRON_INTERVAL_SEC", "5")))
else:
    VIP_CRON_INTERVAL = max(1, int(os.getenv("VIP_CRON_INTERVAL_MIN", "120"))) * 60

JITTER_MAX_SEC = 3 if VIP_TEST_MODE else 7

# ========= مراحل التذكير =========
REMINDER_STAGES: Dict[str, int] = {
    "24h": 24 * 3600,
    "12h": 12 * 3600,
    "6h":   6 * 3600,
    "1h":   1 * 3600,
}
ORDERED_STAGES = list(REMINDER_STAGES.items())

# ======== حالة داخلية ========
_reminder_state: Dict[int, Dict[str, int]] = {}
# _reminder_state[uid] = {"last_expiry_ts": 1700000000, "last_stage_sent_sec": 43200}

# ======== ترجمة موحّدة (نفس منطق الملفات الأخرى) ========
def _L(uid: int) -> str:
    return get_user_lang(uid) or "en"

def _safe_t(lang: str, key: str) -> str | None:
    try:
        s = t(lang, key)
        if isinstance(s, str) and s.strip():
            return s
    except Exception:
        pass
    return None

def _tf(lang: str, key: str, *fallbacks: str) -> str:
    """
    يحاول الترجمة بالترتيب: lang -> en -> ar
    وإن لم يجد، يستخدم البدائل الممررة:
      - إن مرّرت زوج (ar, en) سيختار المناسب حسب اللغة.
      - إن مرّ نص واحد فسيُستخدم للجميع.
    """
    txt = _safe_t(lang, key) or _safe_t("en", key) or _safe_t("ar", key)
    if txt:
        return txt

    ar_fb = en_fb = generic = None
    if len(fallbacks) >= 2:
        ar_fb, en_fb = fallbacks[0], fallbacks[1]
        if len(fallbacks) >= 3:
            generic = fallbacks[2]
    elif len(fallbacks) == 1:
        generic = fallbacks[0]

    if lang.startswith("ar") and ar_fb:
        return ar_fb
    if lang.startswith("en") and en_fb:
        return en_fb
    for v in (en_fb, ar_fb, generic):
        if v:
            return v
    return key

# ======== أدوات مساعدة ========
def _human_delta(seconds: int) -> str:
    s = max(0, int(seconds))
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s: parts.append(f"{s}s")
    return " ".join(parts) if parts else "0s"

def _select_stage(time_left: int) -> Optional[Tuple[str, int]]:
    for name, threshold in ORDERED_STAGES:
        if 0 < time_left <= threshold:
            return name, threshold
    return None

async def _send_stage_reminder(bot, uid: int, stage_name: str, time_left: int, expiry_ts: int):
    lang = _L(uid)
    exp_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(expiry_ts))
    left_h = _human_delta(time_left)

    # نحاول مفتاحًا خاصًا بالمرحلة وإلا نستخدم جنريك
    msg_tpl = _tf(
        lang, f"vip.remind.{stage_name}",
        "⏰ تذكير: سينتهي اشتراك VIP خلال {left}. تاريخ الانتهاء: {expires}",
        "⏰ Reminder: Your VIP will expire in {left}. Expiry: {expires}",
    )
    if msg_tpl.startswith("vip.remind."):  # لم يجد المفتاح
        msg_tpl = _tf(
            lang, "vip.remind.generic",
            "⏰ تذكير: سينتهي اشتراك VIP قريبًا.\nالوقت المتبقي: {left}\nتاريخ/وقت الانتهاء: {expires}",
            "⏰ Reminder: Your VIP subscription will expire soon.\nTime left: {left}\nExpiry: {expires}",
        )

    msg = msg_tpl.format(stage=stage_name, left=left_h, expires=exp_str)
    try:
        await bot.send_message(uid, msg)
        logger.info(f"[VIP REMIND] Sent {stage_name} to {uid}, left={time_left}s, exp={expiry_ts}")
    except Exception as e:
        logger.warning(f"[VIP REMIND] Failed to send reminder to {uid}: {e}")

async def _notify_expired(bot, uids):
    for uid in uids:
        try:
            lang = _L(uid)
            text = _tf(
                lang, "vip.expired_removed",
                "❗ انتهى اشتراكك في VIP وتمت إزالتك من القائمة. يمكنك إعادة التفعيل بالتواصل مع الدعم.",
                "❗ Your VIP subscription has expired and was removed. You can reactivate by contacting support."
            )
            await bot.send_message(uid, text)
            logger.info(f"[VIP EXPIRE] Notified expired user {uid}")
        except Exception as e:
            logger.warning(f"[VIP EXPIRE] Failed to notify {uid}: {e}")
        _reminder_state.pop(uid, None)

async def _expire_notify_and_remove(bot):
    try:
        expired_uids = purge_expired()
    except Exception as e:
        logger.warning(f"[VIP CRON] purge_expired failed: {e}")
        expired_uids = []
    if expired_uids:
        await _notify_expired(bot, expired_uids)

async def _process_reminders(bot):
    try:
        data = list_vips() or {"users": {}}
    except Exception as e:
        logger.warning(f"[VIP REMIND] list_vips failed: {e}")
        return

    users = data.get("users") or {}
    now = _now_ts()

    for uid_str, meta in list(users.items()):
        try:
            uid = int(uid_str)
        except Exception:
            continue

        exp = (meta or {}).get("expiry_ts")
        if not isinstance(exp, int):
            _reminder_state.pop(uid, None)  # مدى الحياة: لا تذكير
            continue

        time_left = exp - now
        if time_left <= 0:
            continue
        if not VIP_REMIND_ENABLED:
            continue

        sel = _select_stage(time_left)
        if not sel:
            continue  # أكثر من 24 ساعة

        stage_name, stage_sec = sel
        st = _reminder_state.get(uid)
        if st is None:
            _reminder_state[uid] = {"last_expiry_ts": exp, "last_stage_sent_sec": 0}
            st = _reminder_state[uid]

        # تمديد الاشتراك: صفّر المراحل
        if exp > st.get("last_expiry_ts", 0):
            logger.info(f"[VIP REMIND] Extension detected: uid={uid} {st.get('last_expiry_ts')} -> {exp}")
            st["last_expiry_ts"] = exp
            st["last_stage_sent_sec"] = 0

        last_sent = st.get("last_stage_sent_sec", 0)
        if last_sent == 0 or stage_sec < last_sent:
            await _send_stage_reminder(bot, uid, stage_name, time_left, exp)
            st["last_stage_sent_sec"] = stage_sec
            st["last_expiry_ts"] = exp

async def _tick(bot):
    await _expire_notify_and_remove(bot)
    await _process_reminders(bot)

async def run_vip_cron(bot):
    """
    شغّلها من البوت:
        asyncio.create_task(run_vip_cron(bot))
    """
    logger.info(
        f"[VIP CRON] Starting | test_mode={VIP_TEST_MODE} | "
        f"interval={VIP_CRON_INTERVAL}s | reminders={'on' if VIP_REMIND_ENABLED else 'off'}"
    )
    try:
        await _tick(bot)
    except Exception as e:
        logger.warning(f"[VIP CRON] First tick failed: {e}")

    while True:
        try:
            sleep_for = VIP_CRON_INTERVAL + random.randint(0, JITTER_MAX_SEC)
            await asyncio.sleep(sleep_for)
            await _tick(bot)
        except Exception as e:
            logger.warning(f"[VIP CRON] Tick failed: {e}")
