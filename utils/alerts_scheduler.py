# utils/alerts_scheduler.py
from __future__ import annotations

import asyncio, json, time, os, threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from aiogram import Bot

# نستخدم برودكاست الحالي لديك (التوقيع: text_en, text_ar, kind, delivery, ping_ttl, active_for)
from utils.alerts_broadcast import broadcast

# مجلد تخزين دائم موحّد
from utils.paths import BASE

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


# ─────────── API عام للجدولة ───────────
def enqueue_job(
    ts: int,
    kind: str,
    en: Optional[str],
    ar: Optional[str],
    *,
    delivery: str = "inbox",     # "inbox" أو "push"
    ping_ttl: int = 0,           # يحذف رسالة التنبيه بعد n ثواني (للـ inbox/push)
    active_for: int = 7 * 24 * 3600,  # مدة بقاء الإشعار في الصندوق
) -> str:
    """
    يضيف مهمة بث تُنفّذ عند الطابع الزمني ts (ثواني).
    يعيد job_id.
    """
    import uuid
    j = {
        "id": uuid.uuid4().hex[:10],
        "ts": int(ts),
        "kind": str(kind or "app_update"),
        "en": en,
        "ar": ar,
        "delivery": str(delivery or "inbox"),
        "ping_ttl": int(ping_ttl or 0),
        "active_for": int(active_for or 0),
        "created_at": int(time.time()),
    }
    jobs = _jobs()
    jobs.append(j)
    _save_jobs(jobs)
    return j["id"]

def list_jobs() -> List[Dict[str, Any]]:
    """يعيد قائمة الوظائف المجدولة (غير المنفذة بعد)."""
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
                break  # لأن list_jobs مرتبة تصاعدياً

            # نفّذ البث
            en = j.get("en")
            ar = j.get("ar")
            kind = j.get("kind") or "app_update"
            delivery = j.get("delivery") or "inbox"
            ping_ttl = int(j.get("ping_ttl") or 0)
            active_for = int(j.get("active_for") or (7 * 24 * 3600))

            try:
                await broadcast(
                    _bot,
                    text_en=en,
                    text_ar=ar,
                    kind=kind,
                    delivery=delivery,     # "inbox" | "push"
                    ping_ttl=ping_ttl,     # كان سابقاً ttl_seconds
                    active_for=active_for, # مدة بقاءه في الصندوق
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
