import json, os
from pathlib import Path

UID = 7360982123
ROLE = "admin"

def _load(p: Path):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)

# BASE (fallback إلى ./data)
try:
    from utils.paths import BASE as _BASE
    BASE = Path(_BASE) if not isinstance(_BASE, Path) else _BASE
except Exception:
    BASE = Path("data")

roles_p = BASE / "admin_roles.json"
block_p = BASE / "live_blocklist.json"

# 1) أضِفه كـ admin
roles = _load(roles_p)
roles[str(UID)] = ROLE
_save(roles_p, roles)

# 2) ارفعه من البلوك (إن وُجد)
bl = _load(block_p)
if str(UID) in bl:
    bl.pop(str(UID), None)
    _save(block_p, bl)

print("[ok] roles/admin_roles.json updated: set admin")
print("[ok] live_blocklist.json cleaned (if existed)")

print("\nتذكير مهم:")
print(" - أضِف الـ UID إلى ADMIN_IDS في .env أو utils/admins.py")
print(" - أعد تشغيل البوت")
