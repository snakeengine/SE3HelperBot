# utils/rewards_flags.py
from __future__ import annotations
import json, os
from pathlib import Path

FLAGS_PATH = Path("data") / "rewards_flags.json"

def _load() -> dict:
    try:
        if FLAGS_PATH.exists():
            return json.loads(FLAGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save(obj: dict):
    FLAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = FLAGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, FLAGS_PATH)

# --------- Query
def is_global_paused() -> bool:
    return bool((_load() or {}).get("global_paused"))

def is_user_paused(uid: int) -> bool:
    return bool((_load() or {}).get("user_paused", {}).get(str(uid)))

def list_paused_users() -> list[int]:
    d = _load(); up = d.get("user_paused") or {}
    out = []
    for k, v in up.items():
        if v: 
            try: out.append(int(k))
            except: pass
    return out

# --------- Mutate
def set_global_paused(v: bool):
    d = _load(); d["global_paused"] = bool(v); _save(d)

def set_user_paused(uid: int):
    d = _load(); up = d.get("user_paused") or {}; up[str(uid)] = True; d["user_paused"] = up; _save(d)

def clear_user_paused(uid: int):
    d = _load(); up = d.get("user_paused") or {}; up.pop(str(uid), None); d["user_paused"] = up; _save(d)

def clear_all_user_paused():
    d = _load(); d["user_paused"] = {}; _save(d)
