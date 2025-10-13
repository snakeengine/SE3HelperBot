import json, os, sys
from pathlib import Path

UID = 7360982123

def _load(p: Path):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save(p: Path, obj):
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except Exception as e:
        print(f"[warn] save {p} failed: {e}")

# حاول نجيب BASE من utils.paths؛ وإلا استخدم ./data
try:
    from utils.paths import BASE as BASE
    if isinstance(BASE, (str, Path)):
        BASE = Path(BASE)
    else:
        BASE = Path("data")
except Exception:
    BASE = Path("data")

files = {
    "roles": BASE / "admin_roles.json",
    "seen":  BASE / "admin_last_seen.json",
    "active": BASE / "live_admin_active.json",
}

# 1) roles  احذف أو نزل الدور
roles = _load(files["roles"])
if str(UID) in roles:
    roles.pop(str(UID), None)
    _save(files["roles"], roles)
    print("[ok] removed from admin_roles.json")
else:
    print("[i] not in admin_roles.json")

# 2) last seen  احذف
seen = _load(files["seen"])
if str(UID) in seen:
    seen.pop(str(UID), None)
    _save(files["seen"], seen)
    print("[ok] removed from admin_last_seen.json")
else:
    print("[i] not in admin_last_seen.json")

# 3) live_admin_active  لو ماسك جلسة انظفه
active = _load(files["active"])
rm = []
for aid, linked_uid in (active or {}).items():
    try:
        if int(aid) == UID or int(linked_uid) == UID:
            rm.append(aid)
    except Exception:
        pass
for k in rm:
    active.pop(k, None)
if rm:
    _save(files["active"], active)
    print("[ok] cleaned live_admin_active.json entries:", rm)
else:
    print("[i] no live_admin_active entries")

print("\nDone. IMPORTANT:")
print(" - Remove the UID from ADMIN_IDS in .env (or utils/admins.py) if present.")
print(" - Restart the bot.")
