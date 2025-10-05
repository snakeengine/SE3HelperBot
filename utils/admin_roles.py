# utils/admin_roles.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, List
from utils.paths import BASE

ROLES_FILE: Path = BASE / "admin_roles.json"
ROLES: List[str] = ["default", "reports", "livechat", "sales"]

def _default_map() -> Dict[str, List[int]]:
    return {r: [] for r in ROLES}

def load_roles() -> Dict[str, List[int]]:
    try:
        if ROLES_FILE.exists():
            data = json.loads(ROLES_FILE.read_text(encoding="utf-8")) or {}
        else:
            data = {}
        # تأكيد الأدوار الأساسية + تنظيف القيم لأرقام صحيحة
        for r in ROLES:
            data.setdefault(r, [])
        cleaned = {}
        for k, v in data.items():
            vv = []
            for x in (v or []):
                sx = str(x).strip()
                if sx.lstrip("-").isdigit():
                    try:
                        vv.append(int(sx))
                    except Exception:
                        pass
            cleaned[k] = vv
        return cleaned
    except Exception:
        return _default_map()

def save_roles(m: Dict[str, List[int]]) -> None:
    try:
        for r in ROLES:
            m.setdefault(r, [])
        ROLES_FILE.parent.mkdir(parents=True, exist_ok=True)
        ROLES_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def role_label(role: str, lang: str) -> str:
    role = (role or "").lower()
    if str(lang).startswith("ar"):
        return {"default":"الافتراضي","reports":"التقارير","livechat":"الدردشة","sales":"المبيعات"}.get(role, role)
    return {"default":"default","reports":"reports","livechat":"livechat","sales":"sales"}.get(role, role)

def fmt_ids(ids: List[int], lang: str) -> str:
    if ids:
        try:
            return ", ".join(str(int(x)) for x in ids)
        except Exception:
            return ", ".join(map(str, ids))
    return "(" + ("فارغ" if str(lang).startswith("ar") else "empty") + ")"

def parse_ids(text: str) -> List[int]:
    out: List[int] = []
    joined = (text or "").replace(",", " ")
    for tok in joined.split():
        tok = tok.strip().lstrip("+")
        if tok.startswith("@"):
            continue
        try:
            out.append(int(tok))
        except Exception:
            continue
    # إزالة التكرار مع الحفاظ على الترتيب
    seen = set(); dedup: List[int] = []
    for v in out:
        if v not in seen:
            seen.add(v); dedup.append(v)
    return dedup

