# middlewares/vip_rate_limit.py
from __future__ import annotations

import os
import time
from collections import deque, defaultdict
from typing import Callable, Awaitable, Any, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

# --- Helpers ---
try:
    from utils.vip_access import has_vip_or_admin
except Exception:
    def has_vip_or_admin(_uid: int) -> bool:
        return False

try:
    from lang import t, get_user_lang
except Exception:
    def t(_lang: str, _key: str) -> str:
        return "⏳ Slow down a bit."
    def get_user_lang(_uid: int) -> str:
        return "en"

def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.getenv(name, "").strip())
        return v if v > 0 else default
    except Exception:
        return default

def _env_set(name: str) -> set[str]:
    return {x.strip() for x in os.getenv(name, "").split(",") if x.strip()}

# === Settings (per-type & per-tier) ===
# Enable/disable
RL_ENABLED = os.getenv("RL_ENABLED", "1").strip() not in ("0", "false", "False", "")

# Message window & caps
VIP_MSG_WINDOW  = _env_int("VIP_RL_MSG_WINDOW", 10)
USR_MSG_WINDOW  = _env_int("USR_RL_MSG_WINDOW", 10)
VIP_MSG_MAX     = _env_int("VIP_RL_MSG_MAX", 12)
USR_MSG_MAX     = _env_int("USR_RL_MSG_MAX", 5)

# Callback window & caps
VIP_CB_WINDOW   = _env_int("VIP_RL_CB_WINDOW", 10)
USR_CB_WINDOW   = _env_int("USR_RL_CB_WINDOW", 10)
VIP_CB_MAX      = _env_int("VIP_RL_CB_MAX", 20)
USR_CB_MAX      = _env_int("USR_RL_CB_MAX", 10)

# Whitelists (separate)
# Commands like /start, /report … (names without slash or @)
MSG_WHITELIST = _env_set("RL_MSG_WHITELIST")    # e.g. "start,report,admin"
# Callback prefixes or full data keys before ":" e.g. "admin", "vip", "maint"
CB_WHITELIST  = _env_set("RL_CB_WHITELIST")     # e.g. "admin,maint,rin"

# Housekeeping
_CLEAN_EVERY   = 2000
_MAX_DEQUE_LEN = 128

class _Bucket:
    """Sliding window bucket per user & type."""
    __slots__ = ("dq",)
    def __init__(self):
        self.dq: deque[float] = deque()

class VipRateLimitMiddleware(BaseMiddleware):
    """
    Per-user sliding window rate limit:
      - Separate limits for Message vs CallbackQuery
      - Separate limits for VIP/Admin vs Regular
      - Separate whitelists for commands & callback prefixes
      - Localized throttle messages
    """
    def __init__(self):
        super().__init__()
        # hits[(uid, "msg"|"cb")] -> deque[timestamps]
        self._hits: Dict[tuple[int, str], _Bucket] = defaultdict(_Bucket)
        self._counter = 0

    # ---------- Whitelists ----------
    def _is_msg_whitelisted(self, msg: Message) -> bool:
        if not MSG_WHITELIST:
            return False
        txt = (msg.text or "").lstrip()
        if not txt.startswith("/"):
            return False
        cmd = txt.split()[0].lstrip("/").split("@", 1)[0]
        return cmd in MSG_WHITELIST

    def _is_cb_whitelisted(self, cb: CallbackQuery) -> bool:
        if not CB_WHITELIST:
            return False
        data = (cb.data or "")
        key = data.split(":", 1)[0] if ":" in data else data
        return key in CB_WHITELIST

    # ---------- Core ----------
    def _allowed(self, uid: int, typ: str, vip: bool) -> bool:
        now = time.monotonic()
        bucket = self._hits[(uid, typ)]
        dq = bucket.dq

        if typ == "msg":
            window = VIP_MSG_WINDOW if vip else USR_MSG_WINDOW
            cap    = VIP_MSG_MAX     if vip else USR_MSG_MAX
        else:
            window = VIP_CB_WINDOW if vip else USR_CB_WINDOW
            cap    = VIP_CB_MAX    if vip else USR_CB_MAX

        # purge
        while dq and (now - dq[0] > window):
            dq.popleft()

        if len(dq) >= cap:
            return False

        dq.append(now)
        if len(dq) > _MAX_DEQUE_LEN:
            while len(dq) > _MAX_DEQUE_LEN:
                dq.popleft()

        self._counter += 1
        if self._counter % _CLEAN_EVERY == 0:
            to_del = [k for k, b in self._hits.items() if not b.dq]
            for k in to_del:
                self._hits.pop(k, None)

        return True

    async def __call__(self,
                       handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject,
                       data: Dict[str, Any]) -> Any:

        if not RL_ENABLED:
            return await handler(event, data)

        uid = None
        typ = None
        if isinstance(event, Message) and event.from_user:
            uid = event.from_user.id
            typ = "msg"
            if self._is_msg_whitelisted(event):
                return await handler(event, data)
        elif isinstance(event, CallbackQuery) and event.from_user:
            uid = event.from_user.id
            typ = "cb"
            if self._is_cb_whitelisted(event):
                return await handler(event, data)

        if uid is None or typ is None:
            return await handler(event, data)

        vip = has_vip_or_admin(uid)

        if not self._allowed(uid, typ, vip):
            try:
                lang = get_user_lang(uid) or "en"
                key = "rate.limit.slow.cb" if typ == "cb" else "rate.limit.slow.msg"
                text = t(lang, key)
            except Exception:
                text = "⏳ Slow down a bit."

            try:
                if isinstance(event, Message):
                    await event.answer(text)
                elif isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=True)
            except Exception:
                pass
            return

        return await handler(event, data)
