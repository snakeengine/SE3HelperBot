# utils/alerts_scheduler.py
from __future__ import annotations
import asyncio, json, time, uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from aiogram import Bot
from .alerts_broadcast import broadcast, _load_json, _save_json

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
JOBS_FILE = DATA_DIR / "alerts_jobs.json"

_loop_task: Optional[asyncio.Task] = None
_bot: Optional[Bot] = None

def _jobs() -> List[Dict[str, Any]]:
    return _load_json(JOBS_FILE) or []

def _save_jobs(jobs: List[Dict[str, Any]]) -> None:
    _save_json(JOBS_FILE, jobs)

def enqueue_job(ts: int, kind: str, en: str | None, ar: str | None, ttl: int = 0) -> str:
    j = {"id": uuid.uuid4().hex[:10], "ts": int(ts), "kind": kind, "en": en, "ar": ar, "ttl": int(ttl)}
    jobs = _jobs(); jobs.append(j); _save_jobs(jobs)
    return j["id"]

def list_jobs() -> List[Dict[str, Any]]:
    return _jobs()

def cancel_job(jid: str) -> bool:
    jobs = _jobs()
    n = len(jobs)
    jobs = [j for j in jobs if j.get("id") != jid]
    _save_jobs(jobs)
    return len(jobs) != n

def cancel_all_jobs() -> int:
    n = len(_jobs()); _save_jobs([]); return n

async def _scheduler_loop():
    global _bot
    assert _bot is not None
    while True:
        now = int(time.time())
        jobs = sorted(_jobs(), key=lambda x: int(x.get("ts", 0)))
        changed = False
        for j in list(jobs):
            if int(j.get("ts", 0)) <= now:
                en = j.get("en"); ar = j.get("ar"); kind = j.get("kind") or "app_update"; ttl = int(j.get("ttl") or 0)
                await broadcast(_bot, text_en=en, text_ar=ar, kind=kind, ttl_seconds=ttl)
                jobs.remove(j); changed = True
        if changed:
            _save_jobs(jobs)
        await asyncio.sleep(5)

async def init_alerts_scheduler(bot: Bot):
    """Call this once at startup."""
    global _loop_task, _bot
    _bot = bot
    if _loop_task is None or _loop_task.done():
        _loop_task = asyncio.create_task(_scheduler_loop())
