from __future__ import annotations

# لا يضمّن أي Router — مجرد patch خفيف يعمل وقت الاستيراد فقط


from typing import Optional

# 1) نقرأ الهدف الحالي من مركز الإدارة
try:
    from admin.admin_center import current_target, register_binding
except Exception as e:
    current_target = lambda k: None  # fallback
    register_binding = lambda k, fn: None

# 2) نرقّع live_chat بدون لمس ملفه
try:
    import handlers.live_chat as live_mod
except Exception:
    live_mod = None

def _chosen_support_id() -> Optional[int]:
    """
    يقرأ مستلم مفتاح support من /adm_center.
    يعيد None إذا ما فيه اختيار.
    """
    try:
        v = current_target("support")
        return int(v) if v else None
    except Exception:
        return None

def _targets_patch() -> list[int]:
    """
    بديل للدالة الأصلية live_mod._targets:
    - إن تم اختيار مستلم support في مركز الإدارة => نرسل له فقط
    - غير ذلك => نرجع للقائمة القديمة ADMIN_IDS
    """
    uid = _chosen_support_id()
    if uid:
        return [uid]
    # fallback: لا نكسر أي سلوك قديم
    try:
        return [int(x) for x in live_mod.ADMIN_IDS]
    except Exception:
        return []

def _apply_support(uid: Optional[int]) -> None:
    """
    تُستدعى عندما تغيّر الهدف في /adm_center.
    لا نحتاج أكثر من ذلك لأن _targets_patch تقرأ القيمة كل مرة.
    لكن نترك الهوك للمستقبل.
    """
    return  # لا شيء

# فعّل الترقيع عند الاستيراد
if live_mod is not None:
    # غيّر دالة اختيار المستلمين فقط — بدون أي include أو لمس للراوتر
    try:
        live_mod._targets = _targets_patch
    except Exception:
        pass

# سجّل الربط مع مركز الإدارة (حتى إذا غيّرت الهدف يُستدعى الهوك)
try:
    register_binding("support", _apply_support)
except Exception:
    pass
