# admin/sevip_activation_admin.py
from __future__ import annotations
import os, json, time, random, string, logging
from pathlib import Path
from typing import Dict, Any, List

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="sevip_activation_admin")
log = logging.getLogger(__name__)

DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
KEYS_FILE = DATA_DIR / "sevip_keys.json"

_admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(x) for x in str(_admin_env).split(",") if str(x).strip().isdigit()]

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS if ADMIN_IDS else False

def _load() -> Dict[str, Any]:
    if KEYS_FILE.exists():
        try: return json.loads(KEYS_FILE.read_text(encoding="utf-8"))
        except Exception: pass
    return {"keys": {}}

def _save(d: Dict[str, Any]) -> None:
    tmp = KEYS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(KEYS_FILE)

def _gen_key() -> str:
    def part(n): return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))
    return f"SE3-{part(4)}-{part(4)}-{part(4)}"

@router.message(Command("gen_keys"))
async def gen_keys(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    parts = (msg.text or "").split()
    if len(parts) < 3:
        await msg.reply("الاستخدام: /gen_keys <days> <count>")
        return
    try:
        days = int(parts[1]); count = int(parts[2])
        assert days > 0 and 1 <= count <= 200
    except Exception:
        await msg.reply("قِيَم غير صحيحة. مثال: /gen_keys 30 20")
        return

    box = _load()
    created = []
    now = int(time.time())
    for _ in range(count):
        k = _gen_key()
        while k in box["keys"]:
            k = _gen_key()
        box["keys"][k] = {"days": days, "status": "unused", "created_at": now, "created_by": msg.from_user.id}
        created.append(k)
    _save(box)

    preview = "\n".join(created[:30])
    extra = f"\n(+{len(created)-30} أخرى)" if len(created) > 30 else ""
    await msg.reply(f"تم توليد {len(created)} كودًا لمدة {days} يومًا.\n\n{preview}{extra}")

@router.message(Command("list_unused"))
async def list_unused(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    box = _load()
    unused = [k for k, v in box["keys"].items() if v.get("status") == "unused"]
    preview = "\n".join(unused[:60])
    more = f"\n(+{len(unused)-60} أخرى)" if len(unused) > 60 else ""
    await msg.reply(f"غير المستخدمة: {len(unused)}\n\n{preview}{more}")

@router.message(Command("revoke_key"))
async def revoke_key(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("الاستخدام: /revoke_key <CODE>")
        return
    code = parts[1].strip().upper()
    box = _load()
    if code not in box["keys"]:
        await msg.reply("الكود غير موجود.")
        return
    box["keys"][code]["status"] = "revoked"
    _save(box)
    await msg.reply("تم إلغاء الكود.")
