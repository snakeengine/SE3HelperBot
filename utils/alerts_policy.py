from __future__ import annotations

# utils/alerts_policy.py


import json, time, os, random, datetime as dt
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, Set

from utils.paths import BASE
from utils.alerts_config import get_config
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from utils.alerts_config import get_config

ALERTS_DIR: Path = (BASE / "alerts"); ALERTS_DIR.mkdir(parents=True, exist_ok=True)
SIGNALS_FILE: Path = ALERTS_DIR / "user_signals.json"  # { "<uid>": { "last_active":ts, "last_open":ts, "last_push":ts, "opens":int, "ignores":int, "deletes":int, "caps": {"2025-W41": 2}, "dedupe": {"<key>": ts} } }

def _load_json(p: Path):
    if not p.exists(): return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

def _save_json(p: Path, data: Any):
    tmp = p.with_suffix(p.suffix + f".{int(time.time()*1000)}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)

def _iso_week(ts: Optional[int] = None) -> str:
    d = dt.datetime.utcfromtimestamp(ts or int(time.time()))
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"

def load_signals() -> Dict[str, Any]:
    return _load_json(SIGNALS_FILE)

def save_signals(d: Dict[str, Any]) -> None:
    _save_json(SIGNALS_FILE, d)

def bump_signal(uid: int, *, event: str) -> None:
    d = load_signals()
    u = d.setdefault(str(uid), {})
    now = int(time.time())
    if event == "open":
        u["last_open"] = now
        u["opens"] = int(u.get("opens", 0)) + 1
    elif event == "ignore":
        u["ignores"] = int(u.get("ignores", 0)) + 1
    elif event == "delete":
        u["deletes"] = int(u.get("deletes", 0)) + 1
    elif event == "active":
        u["last_active"] = now
    save_signals(d)

def _parse_quiet_hours(s: str) -> Tuple[int, int]:
    """
    '22:00-08:00' -> (1320, 480) بالدقائق من بداية اليوم.
    يدعم نافذة عابرة لنهاية اليوم.
    """
    try:
        a, b = s.split("-", 1)
        h1, m1 = map(int, a.split(":"))
        h2, m2 = map(int, b.split(":"))
        return h1*60 + m1, h2*60 + m2
    except Exception:
        return (22*60, 8*60)

def in_quiet_hours(now_local: dt.datetime, quiet_range: str) -> bool:
    start_min, end_min = _parse_quiet_hours(quiet_range)
    cur = now_local.hour*60 + now_local.minute
    if start_min <= end_min:
        return start_min <= cur < end_min
    # نافذة عابرة للمنتصف (مثال 22:00-08:00)
    return (cur >= start_min) or (cur < end_min)

def should_push(uid: int, *, now: Optional[int] = None) -> bool:
    """
    سياسة بسيطة:
    - لو عند المستخدم opens > ignores بشكل واضح خلال 30 يوم → Push
    - لو تجاهل/حذف أكثر → Inbox
    - لو dormant (ما فتح من 21 يوم) → Push مرة كل 2 أسابيع فقط وإلا Inbox
    """
    ts = int(now or time.time())
    d = load_signals().get(str(uid), {})
    last_open = int(d.get("last_open") or 0)
    opens = int(d.get("opens") or 0)
    ignores = int(d.get("ignores") or 0)
    deletes = int(d.get("deletes") or 0)
    last_push = int(d.get("last_push") or 0)

    dormant = (ts - last_open) > (21 * 24 * 3600)
    if dormant:
        # ادفع Push فقط لو مرّ >=14 يوم من آخر Push
        return (ts - last_push) >= (14 * 24 * 3600)

    if opens >= ignores + deletes:
        return True
    return False  # Inbox افتراضيًا

def can_send_by_cap(uid: int, *, max_per_week: int) -> bool:
    d = load_signals()
    u = d.get(str(uid), {})
    wk = _iso_week()
    caps = u.get("caps") or {}
    count = int(caps.get(wk, 0))
    return count < int(max_per_week)

def inc_cap(uid: int) -> None:
    d = load_signals()
    u = d.setdefault(str(uid), {})
    wk = _iso_week()
    caps = u.setdefault("caps", {})
    caps[wk] = int(caps.get(wk, 0)) + 1
    save_signals(d)

def pass_dedupe(uid: int, key: Optional[str], *, window_seconds: int) -> bool:
    """يرفض إرسال نفس الحملة (dedupe_key) لنفس المستخدم ضمن النافذة."""
    if not key:
        return True
    d = load_signals()
    u = d.setdefault(str(uid), {})
    dd = u.setdefault("dedupe", {})
    now = int(time.time())
    ts = int(dd.get(key) or 0)
    if ts and (now - ts) < window_seconds:
        return False
    dd[key] = now
    save_signals(d)
    return True

def mark_pushed(uid: int) -> None:
    d = load_signals()
    u = d.setdefault(str(uid), {})
    u["last_push"] = int(time.time())
    save_signals(d)

def best_send_window_now() -> tuple[bool, int]:
    """
    تُعيد (allowed_now, sleep_seconds).
    - إذا quiet_enabled=False => دائمًا True.
    - إذا quiet_enabled=True وتحديد فترة مثل 22:00-08:00 نمنع الإرسال داخلها.
    """
    cfg = get_config()
    if not bool(cfg.get("quiet_enabled", True)):
        return True, 0

    quiet = str(cfg.get("quiet_hours") or "").strip().lower()
    if quiet in {"", "off", "none"}:
        return True, 0

    try:
        start_s, end_s = quiet.split("-", 1)
        tz = ZoneInfo(str(cfg.get("tz") or "Asia/Baghdad"))
        now = datetime.now(tz)
        hh1, mm1 = [int(x) for x in start_s.split(":")]
        hh2, mm2 = [int(x) for x in end_s.split(":")]
        t1 = dtime(hh1, mm1); t2 = dtime(hh2, mm2)
        now_t = now.timetz()

        def _secs_until(t: dtime) -> int:
            target = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            if target <= now:  # اليوم القادم
                target = target.replace(day=now.day) + timedelta(days=1)
            return int((target - now).total_seconds())

        if t1 == t2:  # 00:00-00:00 => لا هدوء
            return True, 0

        if t1 < t2:
            # هدوء ضمن نفس اليوم
            in_quiet = t1 <= now_t <= t2
        else:
            # فترة ليلية (تعبر منتصف الليل)
            in_quiet = now_t >= t1 or now_t <= t2

        if not in_quiet:
            return True, 0

        # نحن داخل الهدوء -> اقترح النوم حتى نهاية الهدوء
        from datetime import timedelta
        if t1 < t2:
            end_dt = now.replace(hour=t2.hour, minute=t2.minute, second=0, microsecond=0)
            if end_dt <= now: end_dt += timedelta(days=1)
        else:
            # نهاية الهدوء غدًا
            end_dt = now.replace(hour=t2.hour, minute=t2.minute, second=0, microsecond=0) + timedelta(days=1)
        return False, max(1, int((end_dt - now).total_seconds()))
    except Exception:
        # أي خطأ في الصيغة => اعتبرها متاحة
        return True, 0

def jitter_delay(base_delay: float, *, jitter_ms: int = 250) -> float:
    if jitter_ms <= 0: 
        return base_delay
    j = random.uniform(-jitter_ms, jitter_ms) / 1000.0
    return max(0.0, base_delay + j)
