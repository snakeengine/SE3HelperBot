# utils/rewards_store.py
from __future__ import annotations

import json, time, threading
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional, Literal
import datetime as _dt

# ===== مسارات التخزين =====
DATA_DIR = Path("data") / "rewards"
DATA_DIR.mkdir(parents=True, exist_ok=True)

USERS_FILE  = DATA_DIR / "users.json"
ORDERS_FILE = DATA_DIR / "orders.json"
ITEMS_FILE  = DATA_DIR / "items.json"   # كتالوج اختياري

_LOCK = threading.Lock()
_MAX_HISTORY = 300  # الحد الأقصى لسجل كل مستخدم (الأحدث أولًا)

# ===== أدوات I/O آمنة =====
def _atomic_write(path: Path, data: Any):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw or "null") or default
    except Exception:
        return default

def _now() -> int:
    return int(time.time())

# ===== USERS =====
def _load_users() -> Dict[str, Any]:
    return _load(USERS_FILE, {})

def _save_users(store: Dict[str, Any]):
    _atomic_write(USERS_FILE, store)

def ensure_user(uid: int) -> Dict[str, Any]:
    """يضمن وجود المستخدم ويهيّئ الحقول الحديثة."""
    with _LOCK:
        store = _load_users()
        key = str(int(uid))
        u = store.get(key)
        if not u:
            u = {
                "points": 0,
                "blocked": False,
                "created_at": _now(),
                "updated_at": _now(),
                "last_actions": {},    # {action: ts}
                "daily_date": "",      # "YYYY-MM-DD" (UTC)
                "warns": 0,
                # حقول للسجل والإحصاءات
                "earned": 0,
                "spent": 0,
                "streak": 0,
                "last_claim": None,
                "history": [],         # [{t,type,amount,note}]
            }
            store[key] = u
            _save_users(store)
        else:
            # ترقية الحقول القديمة إن لزم
            u.setdefault("last_actions", {})
            u.setdefault("daily_date", "")
            u.setdefault("warns", 0)
            u.setdefault("earned", 0)
            u.setdefault("spent", 0)
            u.setdefault("streak", 0)
            u.setdefault("last_claim", None)
            u.setdefault("history", [])
            u["updated_at"] = _now()
            store[key] = u
            _save_users(store)
        return u

def _get_user(uid: int) -> Dict[str, Any]:
    ensure_user(uid)
    store = _load_users()
    return store[str(int(uid))]

def _put_user(uid: int, data: Dict[str, Any]):
    with _LOCK:
        store = _load_users()
        store[str(int(uid))] = {**data, "updated_at": _now()}
        _save_users(store)

def get_user(uid: int) -> Dict[str, Any]:
    """إرجاع صف المستخدم كاملًا (للاطّلاع فقط)."""
    return _get_user(uid)

def get_points(uid: int) -> int:
    return int(_get_user(uid).get("points", 0))

def set_blocked(uid: int, blocked: bool):
    u = _get_user(uid)
    u["blocked"] = bool(blocked)
    _put_user(uid, u)

def is_blocked(uid: int) -> bool:
    return bool(_get_user(uid).get("blocked", False))

def mark_warn(uid: int, reason: str = ""):
    u = _get_user(uid)
    u["warns"] = int(u.get("warns", 0)) + 1
    _put_user(uid, u)

# ===== HISTORY =====
def _push_history(u: Dict[str, Any], typ: str, amount: int, note: str = "") -> None:
    """إدراج حركة في بداية السجل مع قصّ الطول."""
    h: List[Dict[str, Any]] = u.setdefault("history", [])
    h.insert(0, {
        "t": _now(),
        "type": str(typ),
        "amount": int(amount),
        "note": str(note or "")
    })
    if len(h) > _MAX_HISTORY:
        del h[_MAX_HISTORY:]

def log_history(uid: int, typ: str, amount: int, note: str = "") -> None:
    """واجهة عامة لتسجيل حركة من أي مكان خارجي."""
    with _LOCK:
        store = _load_users()
        key = str(int(uid))
        u = store.get(key) or ensure_user(uid)
        _push_history(u, typ, int(amount), note)
        store[key] = u
        _save_users(store)

def get_history(uid: int, offset: int = 0, limit: int = 10) -> Tuple[List[Dict[str, Any]], int]:
    """قراءة سجل المستخدم (الأحدث أولًا) مع ترقيم صفحات. ترجع (list, total)."""
    u = _get_user(uid)
    h: List[Dict[str, Any]] = list(u.get("history", []))
    total = len(h)
    return h[offset: offset + max(0, int(limit))], total

def _recalc_agg_from_history(u: Dict[str, Any]) -> None:
    """إعادة حساب earned/spent من السجل فقط (لا نغيّر الرصيد)."""
    hist: List[Dict[str, Any]] = list(u.get("history") or [])
    up = sum(max(0, int(r.get("amount", 0))) for r in hist)
    down = sum(-min(0, int(r.get("amount", 0))) for r in hist)
    u["earned"] = int(up)
    u["spent"] = int(down)

def replace_history(uid: int, new_history: List[Dict[str, Any]]) -> None:
    """
    استبدل سجل المستخدم بالكامل واحفظه فورًا.
    لا يغيّر points، فقط history و earned/spent.
    """
    with _LOCK:
        store = _load_users()
        key = str(int(uid))
        u = store.get(key) or ensure_user(uid)
        u["history"] = list(new_history or [])[:_MAX_HISTORY]
        _recalc_agg_from_history(u)
        u["updated_at"] = _now()
        store[key] = u
        _save_users(store)

# ===== تصنيف تلقائي للنوع =====
def _infer_type(reason: str, delta: int) -> str:
    r = (reason or "").lower().strip()
    # تعديلات الأدمن -> نوع "adjust"
    if r in ("admin_set", "admin_grant", "admin_zero") or r.startswith("admin_"):
        return "adjust"
    if r.startswith("wallet_transfer_out") or r.startswith("to ") or r.startswith("to:") or "transfer_to" in r:
        return "send"
    if r.startswith("wallet_transfer_in") or r.startswith("from ") or r.startswith("from:") or "transfer_from" in r:
        return "recv"
    if r.startswith("market_buy_"):
        return "buy"
    if "refund" in r or r.startswith("vip_order_refund") or r.startswith("market_refund"):
        return "refund"
    if "left_required_channel" in r or "gate" in r:
        return "gate"
    if r.startswith("daily"):
        return "daily"
    if r.startswith("create:") or r.startswith("order"):
        return "order"
    if r.startswith("bonus") or r.startswith("task"):
        return "bonus"
    return "admin"  # احتياطي


# ===== نقاط: إضافة/خصم/شراء/تحويل =====
def add_points(uid: int, delta: int, reason: str = "", typ: str = "admin") -> int:
    """
    إضافة/خصم نقاط (delta قد يكون سالبًا).
    يحدّث earned/spent ويسجّل في السجل.
    """
    with _LOCK:
        store = _load_users()
        key = str(int(uid))
        u = store.get(key) or ensure_user(uid)

        pts_before = int(u.get("points", 0))
        pts_after  = max(0, pts_before + int(delta))
        u["points"] = pts_after

        if delta >= 0:
            u["earned"] = int(u.get("earned", 0)) + int(delta)
        else:
            u["spent"] = int(u.get("spent", 0)) + abs(int(delta))

        typ_eff = typ or "admin"
        # لو الاستدعاء القديم ما مرّر النوع، نحدده من الـ reason
        if typ_eff == "admin":
            typ_eff = _infer_type(reason, int(delta))

        _push_history(u, typ_eff, int(delta), reason or "")
        u["updated_at"] = _now()
        store[key] = u
        _save_users(store)
        return int(u["points"])

def spend_points(uid: int, amount: int, note: str = "", typ: str = "buy") -> bool:
    """خصم نقاط لشراء عنصر. يسجّل السجل. يرجع False إذا الرصيد لا يكفي."""
    amount = int(amount)
    if amount <= 0:
        return False
    with _LOCK:
        store = _load_users()
        key = str(int(uid))
        u = store.get(key) or ensure_user(uid)
        pts = int(u.get("points", 0))
        if pts < amount:
            return False
        u["points"] = pts - amount
        u["spent"]  = int(u.get("spent", 0)) + amount
        _push_history(u, typ or "buy", -amount, note or "")
        store[key] = u
        _save_users(store)
        return True

# ملاحظة: هذه الدالة باقية للتوافق.
def send_points(src: int, dst: int, amount: int, note: str = "") -> Tuple[bool, str]:
    if int(src) == int(dst):
        return False, "لا يمكنك التحويل لنفسك."
    if int(amount) < 5:
        return False, "الحد الأدنى للتحويل 5 نقاط."
    if get_points(src) < int(amount):
        return False, "رصيدك لا يكفي."
    if not can_do(src, "tx_rate", cooldown_sec=20):
        return False, "التحويلات متقاربة جدًا."

    ok = spend_points(src, int(amount), note or f"to:{dst}", typ="send")
    if not ok:
        return False, "رصيدك لا يكفي."
    add_points(dst,  int(amount), note or f"from:{src}", typ="recv")
    return True, "OK"

# ===== Anti-abuse / تبريد =====
def can_do(uid: int, action: str, cooldown_sec: int = 5) -> bool:
    u = _get_user(uid)
    last = int(u.get("last_actions", {}).get(action, 0))
    if _now() - last < int(cooldown_sec):
        return False
    u.setdefault("last_actions", {})[action] = _now()
    _put_user(uid, u)
    return True

def mark_action(uid: int, action: str, when: int | None = None) -> bool:
    """ختم زمن تنفيذ أكشن معيّن بدون فحص كولداون."""
    u = _get_user(uid)
    u.setdefault("last_actions", {})[str(action)] = int(when or _now())
    _put_user(uid, u)
    return True

# ===== Daily claim =====
def daily_claim(uid: int, amount: int = 10) -> Tuple[bool, int]:
    """
    مطالبة يومية مرّة واحدة لكل يوم تقويمي (UTC).
    تُحدّث streak وتسجّل في السجل.
    """
    with _LOCK:
        store = _load_users()
        key = str(int(uid))
        u = store.get(key) or ensure_user(uid)

        today = _dt.datetime.utcnow().strftime("%Y-%m-%d")
        if u.get("daily_date") == today:
            return False, 0

        # تحديث سلسلة الأيام
        prev_date = u.get("daily_date", "")
        if prev_date:
            try:
                d_prev = _dt.datetime.strptime(prev_date, "%Y-%m-%d").date()
                d_now  = _dt.datetime.strptime(today, "%Y-%m-%d").date()
                u["streak"] = u.get("streak", 0) + 1 if (d_now - d_prev).days == 1 else 1
            except Exception:
                u["streak"] = 1
        else:
            u["streak"] = 1

        u["daily_date"] = today
        u["last_claim"] = _now()
        u["points"] = int(u.get("points", 0)) + int(amount)
        u["earned"] = int(u.get("earned", 0)) + int(amount)
        _push_history(u, "daily", int(amount), "daily")

        store[key] = u
        _save_users(store)
        return True, int(amount)

# ===== ITEMS / ORDERS (خفيف) =====
def _load_orders() -> Dict[str, Any]:
    return _load(ORDERS_FILE, {"seq": 1, "orders": []})

def _save_orders(store: Dict[str, Any]):
    _atomic_write(ORDERS_FILE, store)

def list_items() -> List[Dict[str, Any]]:
    """كتالوج افتراضي بسيط، أو من items.json إن وُجد."""
    if ITEMS_FILE.exists():
        try:
            data = json.loads(ITEMS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return [
        {"id": "gift10", "title": "هديّة 10 نقاط", "cost": 10},
        {"id": "gift50", "title": "هديّة 50 نقطة", "cost": 50},
        {"id": "vip",    "title": "ترقية VIP (رمزية)", "cost": 80},
    ]

def get_item(item_id: str) -> Optional[Dict[str, Any]]:
    for it in list_items():
        if str(it.get("id")) == str(item_id):
            return it
    return None

def create_order(uid: int, item_id: str, cost: int, payload: Dict[str, Any]) -> int:
    """إنشاء طلب (بدون الخصم تلقائيًا — خصم النقاط يتم في منطق المتجر)."""
    with _LOCK:
        store = _load_orders()
        order_id = int(store.get("seq", 1))
        store["seq"] = order_id + 1
        store["orders"].append({
            "id": order_id,
            "uid": int(uid),
            "item_id": item_id,
            "cost": int(cost),
            "payload": payload or {},
            "status": "new",
            "created_at": _now()
        })
        _save_orders(store)
        # سجّل إنشاء الطلب (معلومة)
        log_history(uid, "order", 0, f"create:{item_id}#{order_id}")
        return order_id

def list_orders(uid: int) -> List[Dict[str, Any]]:
    store = _load_orders()
    return [o for o in store.get("orders", []) if int(o.get("uid")) == int(uid)]

# ===== أدوات مساعدة زمنية للسجل + الحذف =====
def _now_ts() -> int:
    return int(time.time())

def _start_of_today_ts(now: Optional[int] = None) -> int:
    now = int(now or _now_ts())
    dt = _dt.datetime.fromtimestamp(now)
    sod = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(sod.timestamp())

def _get_tx_list_container(u: dict) -> tuple[str, list]:
    """
    يحاول إيجاد مفتاح السجل عند المستخدم: tx أو history (الأكثر شيوعًا).
    يعيد (key, list_ref) ويضمن وجوده كقائمة.
    """
    if isinstance(u.get("tx"), list):
        return "tx", u["tx"]
    if isinstance(u.get("history"), list):
        return "history", u["history"]
    # أنشئ حاوية فارغة إذا لم تكن موجودة
    u.setdefault("tx", [])
    return "tx", u["tx"]

def _tx_ts(rec: dict) -> int:
    """يحصل على توقيت العملية من مفاتيح شائعة."""
    for k in ("ts", "time", "t", "at"):
        v = rec.get(k)
        if v is not None:
            try:
                return int(v)
            except Exception:
                pass
    return 0

def purge_user_history(
    uid: int,
    *,
    scope: Literal["all", "today", "7d", "30d"] = "all",
) -> int:
    """
    يحذف عناصر من سجل المستخدم فقط (لا يغيّر الرصيد) ويحفظ التغيير.
    """
    with _LOCK:
        store = _load_users()
        key = str(int(uid))
        u = store.get(key) or ensure_user(uid)

        list_key, tx = _get_tx_list_container(u)
        if not isinstance(tx, list) or not tx:
            u[list_key] = []
            store[key] = u
            _save_users(store)
            return 0

        now = _now_ts()
        sod = _start_of_today_ts(now)

        def to_keep(rec: dict) -> bool:
            ts = _tx_ts(rec)
            if scope == "all":
                return False
            if scope == "today":
                return ts < sod
            if scope == "7d":
                cutoff = now - 7 * 86400
                return ts < cutoff
            if scope == "30d":
                cutoff = now - 30 * 86400
                return ts < cutoff
            return True

        original = list(tx)
        kept = [r for r in original if to_keep(r)]
        removed = len(original) - len(kept)

        u[list_key] = kept
        if list_key != "history" and isinstance(u.get("history"), list):
            u["history"] = kept

        try:
            _recalc_agg_from_history(u)
        except Exception:
            pass

        u["updated_at"] = _now()
        store[key] = u
        _save_users(store)
        return removed
# ===== قائمة المحظورين مع ترقيم الصفحات =====
def list_blocked_users(offset: int = 0, limit: int = 20):
    """
    يرجع: (items, total)
      items: [(uid:int, row:dict), ...] مرتّبة بالأحدث تحديثًا.
    """
    store = _load_users()
    entries: List[tuple[int, Dict[str, Any]]] = []
    for uid_s, row in (store or {}).items():
        try:
            if (row or {}).get("blocked"):
                entries.append((int(uid_s), row or {}))
        except Exception:
            continue
    entries.sort(key=lambda x: int(x[1].get("updated_at", 0)), reverse=True)
    total = len(entries)
    items = entries[offset: offset + limit]
    return items, total
