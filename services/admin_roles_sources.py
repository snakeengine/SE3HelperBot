# services/admin_roles_sources.py
from __future__ import annotations
from typing import Dict, List, Set

def _to_ids(x) -> Set[int]:
    out: Set[int] = set()
    if x is None:
        return out
    if isinstance(x, (list, tuple, set)):
        for v in x:
            try:
                out.add(int(v))
            except Exception:
                pass
        return out
    if isinstance(x, str):
        for tok in x.replace(";", ",").split(","):
            tok = tok.strip()
            if tok:
                try:
                    out.add(int(tok))
                except Exception:
                    pass
        return out
    try:
        out.add(int(x))
    except Exception:
        pass
    return out

def read_legacy_admins() -> Dict[str, List[int]]:
    """
    يحاول القراءة من عدة ملفات/موديولات قديمة إن وُجدت:
      - admin/admins.py: ADMINS_DEFAULT / ADMINS_LIVECHAT / ADMINS_REPORTS
      - admin/config.py: ADMIN_IDS / LIVECHAT_ADMINS / REPORT_ADMINS
      - admin/settings.py: ADMIN_IDS / ADMIN_IDS_LIVECHAT / ADMIN_IDS_REPORTS
    ويعيد خريطة للأدوار: default / livechat / reports
    """
    roles: Dict[str, Set[int]] = {"default": set(), "livechat": set(), "reports": set()}

    # 1) admin/admins.py
    try:
        from admin import admins as A
        roles["default"]  |= _to_ids(getattr(A, "ADMINS_DEFAULT", None))
        roles["livechat"] |= _to_ids(getattr(A, "ADMINS_LIVECHAT", None))
        roles["reports"]  |= _to_ids(getattr(A, "ADMINS_REPORTS", None))
    except Exception:
        pass

    # 2) admin/config.py
    try:
        from admin import config as C
        roles["default"]  |= _to_ids(getattr(C, "ADMIN_IDS", None))
        roles["livechat"] |= _to_ids(getattr(C, "LIVECHAT_ADMINS", None))
        roles["reports"]  |= _to_ids(getattr(C, "REPORT_ADMINS", None))
    except Exception:
        pass

    # 3) admin/settings.py
    try:
        from admin import settings as S
        roles["default"]  |= _to_ids(getattr(S, "ADMIN_IDS", None))
        roles["livechat"] |= _to_ids(getattr(S, "ADMIN_IDS_LIVECHAT", None))
        roles["reports"]  |= _to_ids(getattr(S, "ADMIN_IDS_REPORTS", None))
    except Exception:
        pass

    return {k: sorted(v) for k, v in roles.items()}
