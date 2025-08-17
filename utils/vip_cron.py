# utils/vip_cron.py
from __future__ import annotations
import os, time, asyncio, random, logging
from typing import Dict, Optional, Tuple

from utils.vip_store import list_vips, _now_ts, purge_expired

logger = logging.getLogger(__name__)

# ========= الإعدادات من .env =========
# وضع الاختبار: يفعّل القراءة من VIP_CRON_INTERVAL_SEC ويُبقي كل شيء حيّ كل عدة ثوانٍ
VIP_TEST_MODE        = os.getenv("VIP_TEST_MODE", "0").strip() not in ("0", "false", "False", "")
VIP_REMIND_ENABLED   = os.getenv("VIP_REMIND_ENABLED", "1").strip() not in ("0", "false", "False", "")

# فترة الفحص الدوري (ثوانٍ)
if VIP_TEST_MODE:
    VIP_CRON_INTERVAL = max(1, int(os.getenv("VIP_CRON_INTERVAL_SEC", "5")))
else:
    VIP_CRON_INTERVAL = max(1, int(os.getenv("VIP_CRON_INTERVAL_MIN", "120"))) * 60

JITTER_MAX_SEC       = 3 if VIP_TEST_MODE else 7   # عشوائية خفيفة للفصل بين النسخ

# ========= مراحل التذكير (حقيقية) =========
# ترتيب من الأبعد إلى الأقرب قبل الانتهاء
REMINDER_STAGES: Dict[str, int] = {
    "24h": 24 * 3600,
    "12h": 12 * 3600,
    "6h":   6 * 3600,
    "1h":   1 * 3600,
}
ORDERED_STAGES = list(REMINDER_STAGES.items())  # [("24h", 86400), ("12h", 43200), ("6h", 21600), ("1h", 3600)]

# ======== حالة داخلية لمنع التكرار وللتعامل مع التمديد ========
# لكل مستخدم: آخر مرحلة أرسِلَت له + آخر expiry_ts شوهد
_reminder_state: Dict[int, Dict[str, int]] = {}
# _reminder_state[uid] = {"last_expiry_ts": 1700000000, "last_stage_sent_sec": 43200}

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
    """يعيد المرحلة المناسبة بناءً على الوقت المتبقي (أول threshold أكبر من الوقت المتبقي)."""
    for name, threshold in ORDERED_STAGES:
        if 0 < time_left <= threshold:
            return name, threshold
    return None

async def _send_stage_reminder(bot, uid: int, stage_name: str, time_left: int, expiry_ts: int):
    exp_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(expiry_ts))
    msg = (
        f"⏰ تذكير: سينتهي اشتراك VIP قريبًا (مرحلة {stage_name}).\n"
        f"الوقت المتبقي: {_human_delta(time_left)}\n"
        f"تاريخ/وقت الانتهاء: {exp_str}"
    )
    try:
        await bot.send_message(uid, msg)
        logger.info(f"[VIP REMIND] Sent {stage_name} to {uid}, left={time_left}s, exp={expiry_ts}")
    except Exception as e:
        logger.warning(f"[VIP REMIND] Failed to send reminder to {uid}: {e}")

async def _notify_expired(bot, uids):
    """إخطار كل مستخدم انتهى اشتراكه."""
    for uid in uids:
        try:
            await bot.send_message(
                uid,
                "❗ انتهى اشتراكك في VIP وتمت إزالتك من القائمة. يمكنك إعادة التفعيل بالتواصل مع الدعم."
            )
            logger.info(f"[VIP EXPIRE] Notified expired user {uid}")
        except Exception as e:
            logger.warning(f"[VIP EXPIRE] Failed to notify {uid}: {e}")
        # تنظيف حالة التذكير
        _reminder_state.pop(uid, None)

async def _expire_notify_and_remove(bot):
    """يحذف المنتهين الآن ويُخطرهم (مصدر الحقيقة: purge_expired)."""
    try:
        expired_uids = purge_expired()  # قائمة UIDs المحذوفة
    except Exception as e:
        logger.warning(f"[VIP CRON] purge_expired failed: {e}")
        expired_uids = []
    if expired_uids:
        await _notify_expired(bot, expired_uids)

async def _process_reminders(bot):
    """إرسال التذكيرات المرحلية للمشتركين الذين لم تنتهِ صلاحيتهم بعد."""
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
            _reminder_state.pop(uid, None)  # اشتراك دائم: لا تذكير
            continue

        time_left = exp - now
        # انتهى فعلاً؟ سيُزال ويُخطر في _expire_notify_and_remove
        if time_left <= 0:
            continue

        if not VIP_REMIND_ENABLED:
            continue

        sel = _select_stage(time_left)
        if not sel:
            # أكثر من 24 ساعة — لا تذكير الآن
            continue

        stage_name, stage_sec = sel
        st = _reminder_state.get(uid)

        if st is None:
            _reminder_state[uid] = {"last_expiry_ts": exp, "last_stage_sent_sec": 0}
            st = _reminder_state[uid]

        # لو حصل تمديد وتم تغيير exp إلى مستقبل أبعد — صفّر المراحل
        if exp > st.get("last_expiry_ts", 0):
            logger.info(f"[VIP REMIND] Extension detected: uid={uid} {st.get('last_expiry_ts')} -> {exp}")
            st["last_expiry_ts"] = exp
            st["last_stage_sent_sec"] = 0

        last_sent = st.get("last_stage_sent_sec", 0)
        # أرسل فقط إذا هذه المرحلة أقرب من آخر مرحلة أُرسلت (stage_sec < last_sent)
        if last_sent == 0 or stage_sec < last_sent:
            await _send_stage_reminder(bot, uid, stage_name, time_left, exp)
            st["last_stage_sent_sec"] = stage_sec
            st["last_expiry_ts"] = exp

async def _tick(bot):
    # 1) إشعار وإزالة المنتهين
    await _expire_notify_and_remove(bot)
    # 2) تذكير مرحلي للباقين
    await _process_reminders(bot)

async def run_vip_cron(bot):
    """
    شغّل هذه المهمة بحلقة خلفية من bot.py:
        asyncio.create_task(run_vip_cron(bot))

    - يعتمد على purge_expired() لإزالة المنتهين + إشعارهم فورًا.
    - يرسل تذكيرات 24h/12h/6h/1h قبل الانتهاء.
    - يدعم VIP_TEST_MODE و VIP_CRON_INTERVAL_SEC للاختبار السريع.
    """
    logger.info(
        f"[VIP CRON] Starting | test_mode={VIP_TEST_MODE} | "
        f"interval={VIP_CRON_INTERVAL}s | reminders={'on' if VIP_REMIND_ENABLED else 'off'}"
    )

    # تنفيذ فوري لأول فحص
    try:
        await _tick(bot)
    except Exception as e:
        logger.warning(f"[VIP CRON] First tick failed: {e}")

    # حلقة دورية
    while True:
        try:
            sleep_for = VIP_CRON_INTERVAL + random.randint(0, JITTER_MAX_SEC)
            await asyncio.sleep(sleep_for)
            await _tick(bot)
        except Exception as e:
            logger.warning(f"[VIP CRON] Tick failed: {e}")
