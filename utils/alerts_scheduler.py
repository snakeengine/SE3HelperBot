# utils/alerts_scheduler.py
from __future__ import annotations

import asyncio, json, time, os, threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from aiogram import Bot

# نستخدم برودكاست الحالي لديك
from utils.alerts_broadcast import broadcast
from utils.alerts_policy import best_send_window_now
from utils.paths import BASE

# ─────────── مسارات التخزين ───────────
ALERTS_DIR: Path = BASE / "alerts"
ALERTS_DIR.mkdir(parents=True, exist_ok=True)
JOBS_FILE: Path = ALERTS_DIR / "alerts_jobs.json"

_loop_task: Optional[asyncio.Task] = None
_bot: Optional[Bot] = None
_LOCK = threading.Lock()

# ─────────── أدوات I/O ذرّية آمنة ───────────
def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_name(f"{path.name}.{int(time.time()*1000)}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(payload)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
    os.replace(tmp, path)

def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        raw = path.read_text("utf-8")
        return json.loads(raw or "null")
    except Exception:
        return None

def _save_json(path: Path, data: Any):
    _atomic_write(path, data)

# ─────────── مخزن الوظائف ───────────
def _jobs() -> List[Dict[str, Any]]:
    with _LOCK:
        return _load_json(JOBS_FILE) or []

def _save_jobs(jobs: List[Dict[str, Any]]) -> None:
    with _LOCK:
        _save_json(JOBS_FILE, jobs)

# ─────────── API الجدولة ───────────
def enqueue_job(
    ts: int,
    kind: str,
    en: Optional[str],
    ar: Optional[str],
    *,
    # افتراضيات مصممة للإرسال المباشر عند حلول الموعد
    delivery: str = "push",       # push دائمًا
    ping_ttl: int = 0,
    active_for: int = 7 * 24 * 3600,
    force_push: bool = True,      # إرسال فوري للجميع
    ignore_quiet: bool = True,    # تجاهل ساعات الهدوء
    smart_target: bool = False,   # إيقاف الاستهداف الذكي
    dedupe_key: Optional[str] = None,
    dedupe_window: int = 14 * 24 * 3600,
) -> str:
    import uuid
    j = {
        "id": uuid.uuid4().hex[:10],
        "ts": int(ts),
        "kind": str(kind or "app_update"),
        "en": en,
        "ar": ar,
        "delivery": str(delivery or "push"),
        "ping_ttl": int(ping_ttl or 0),
        "active_for": int(active_for or 0),
        # أعلام التحكم
        "force_push": bool(force_push),
        "ignore_quiet": bool(ignore_quiet),
        "smart_target": bool(smart_target),
        "dedupe_key": dedupe_key,
        "dedupe_window": int(dedupe_window),
        "created_at": int(time.time()),
    }
    jobs = _jobs(); jobs.append(j); _save_jobs(jobs)
    return j["id"]

def list_jobs() -> List[Dict[str, Any]]:
    return sorted(_jobs(), key=lambda x: int(x.get("ts", 0)))

def cancel_job(jid: str) -> bool:
    jobs = _jobs()
    n = len(jobs)
    jobs = [j for j in jobs if j.get("id") != jid]
    _save_jobs(jobs)
    return len(jobs) != n

def cancel_all_jobs() -> int:
    n = len(_jobs())
    _save_jobs([])
    return n

# ─────────── الحلقة الداخلية ───────────
async def _scheduler_loop(poll_interval: int = 5):
    global _bot
    assert _bot is not None, "alerts_scheduler: bot is not initialized"
    while True:
        now = int(time.time())
        jobs = list_jobs()
        changed = False

        for j in jobs:
            due = int(j.get("ts", 0)) <= now
            if not due:
                break  # القائمة مرتبة تصاعدياً

            # احترام/تجاهل ساعات الهدوء وفق العلم المخزن في المهمة
            ignore_quiet_flag = bool(j.get("ignore_quiet", False))
            if not ignore_quiet_flag:
                allowed_now, sleep_s = best_send_window_now()
                if not allowed_now:
                    # أعد الجدولة إلى أول نافذة مسموحة
                    j["ts"] = int(time.time()) + int(sleep_s)
                    jobs = [jj if jj.get("id") != j.get("id") else j for jj in jobs]
                    _save_jobs(jobs)
                    changed = True
                    continue

            # تجهيز حقول البث
            en = j.get("en")
            ar = j.get("ar")
            kind = j.get("kind") or "app_update"
            delivery = j.get("delivery") or "push"
            ping_ttl = int(j.get("ping_ttl") or 0)
            active_for = int(j.get("active_for") or (7 * 24 * 3600))

            # تمكين أعلام التحكّم الخاصة بالبث
            smart_kwargs = {
                "smart_target": bool(j.get("smart_target", False)),
                "target_segment": str(j.get("target_segment", "all")),
                "min_last_open_days": int(j.get("min_last_open_days", 0)),
                "dedupe_key": j.get("dedupe_key"),
                "dedupe_window": int(j.get("dedupe_window", 14 * 24 * 3600)),
                "retry_on_fail": int(j.get("retry_on_fail", 1)),
                "jitter_ms": int(j.get("jitter_ms", 250)),
                "force_push": bool(j.get("force_push", True)),
                "ignore_quiet": bool(j.get("ignore_quiet", True)),
            }

            try:
                await broadcast(
                    _bot,
                    text_en=en,
                    text_ar=ar,
                    kind=kind,
                    delivery=delivery,      # "push" | "inbox"
                    ping_ttl=ping_ttl,
                    active_for=active_for,
                    **smart_kwargs,
                )
            except Exception:
                # لا نوقف الحلقة بسبب فشل بث واحد
                pass

            # أزل المهمة المنفذة
            cancel_job(j.get("id"))
            changed = True

        if not changed:
            await asyncio.sleep(max(1, int(poll_interval)))

# ─────────── التهيئة ───────────
async def init_alerts_scheduler(bot: Bot, *, poll_interval: int = 5):
    """
    استدعِها مرة واحدة عند تشغيل البوت.
    """
    global _loop_task, _bot
    _bot = bot
    if _loop_task is None or _loop_task.done():
        _loop_task = asyncio.create_task(_scheduler_loop(poll_interval=poll_interval))
