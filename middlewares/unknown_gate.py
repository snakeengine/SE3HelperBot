# middlewares/unknown_gate.py
from __future__ import annotations
import os, re, json, time, logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional, Set, Union, List

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from lang import t, get_user_lang

logger = logging.getLogger(__name__)

# نافذة السماح المؤقتة (إيصالات الدفع)
try:
    from utils.receipt_gate import is_allowed as _receipt_is_allowed
except Exception:
    def _receipt_is_allowed(_uid: int, _ctype: str) -> bool:
        return False

def _tr(lang: str, key: str, fallback: str) -> str:
    try:
        txt = t(lang, key)
        if not isinstance(txt, str) or not txt.strip() or txt.strip() == key:
            return fallback
        return txt
    except Exception:
        return fallback

class UnknownGateMiddleware(BaseMiddleware):
    """
    يمنع الرسائل "غير المعروفة".
    جديد:
      - fsm_bypass: تجاوز المنع أثناء حالة FSM معيّنة (مثلاً جلسة /report) لأي نوع محتوى.
      - allow_text_if_state: سماح النص أثناء FSM (متوافق مع الإصدارات السابقة).
      - نافذة إيصال الدفع تسمح مؤقتًا ببعض الأنواع (photo/document/text).
    """

    def __init__(
        self,
        *,
        # سياسة الرسائل
        block_unknown_messages: bool = True,
        allow_commands: Iterable[str] = ("start", "help", "lang", "about", "report", "admin"),
        allowed_content_types: Iterable[str] = ("text",),
        allow_free_text: bool = False,
        allow_text_regex: Iterable[str] = (),
        private_only: bool = True,
        notify_cooldown_seconds: int = 10,

        # ✅ مفاتيح الترجمة
        i18n_key_unknown_msg: str = "unknown_gate.unknown_message",
        i18n_key_unknown_user: str = "unknown_gate.unknown_user",

        # 🔹 سماح نص أثناء حالة FSM (قديم)
        allow_text_if_state: bool = True,
        state_whitelist: Optional[Iterable[str]] = None,  # مثلاً {"PromoterApply:name"}

        # 🔹 جديد: تجاوز المنع بالكامل أثناء FSM
        fsm_bypass: bool = False,
        fsm_whitelist: Optional[Iterable[str]] = None,     # مثلاً {"report:collect"}

        # سياسة المستخدمين (اختياري)
        enforce_known_users: bool = False,
        known_users_file: Union[str, Path] = "data/users.json",
        extra_hint_files: Optional[Iterable[Union[str, Path]]] = ("user_langs.json",),
        admin_ids: Optional[Iterable[int]] = None,
        cache_ttl_seconds: int = 15,
    ) -> None:
        super().__init__()
        # سياسة الرسائل
        self.block_unknown_messages = bool(block_unknown_messages)
        self.allow_commands = {self._normalize_cmd(c) for c in allow_commands}
        self.allowed_content_types = {str(ct).lower() for ct in allowed_content_types}
        self.allow_free_text = bool(allow_free_text)
        self.allow_text_regex: List[re.Pattern] = [re.compile(p, re.I | re.S) for p in allow_text_regex]
        self.private_only = bool(private_only)
        self.notify_cooldown = max(5, int(notify_cooldown_seconds))
        self.i18n_key_unknown_msg = i18n_key_unknown_msg
        self.i18n_key_unknown_user = i18n_key_unknown_user

        # سماح نص أثناء الحالة (قديم)
        self.allow_text_if_state = bool(allow_text_if_state)
        self.state_whitelist = set(state_whitelist) if state_whitelist else None

        # جديد: تجاوز المنع أثناء FSM
        self.fsm_bypass = bool(fsm_bypass)
        self.fsm_whitelist = set(fsm_whitelist) if fsm_whitelist else set()

        # سياسة المستخدمين
        self.enforce_known_users = bool(enforce_known_users)
        self.known_users_file = Path(known_users_file)
        self.extra_hint_files = [Path(p) for p in (extra_hint_files or [])]
        self.cache_ttl = max(5, int(cache_ttl_seconds))
        self._known_cache: Set[int] = set()
        self._last_load_ts: float = 0.0

        # ADMIN_IDS
        if admin_ids is None:
            _env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", "")
            try:
                admin_ids = [int(x) for x in str(_env).split(",") if str(x).strip().isdigit()]
            except Exception:
                admin_ids = []
        self.admin_ids: Set[int] = set(admin_ids or [])

        self._last_notified: Dict[int, float] = {}

    async def __call__(self, handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: Dict[str, Any]) -> Any:
        user = data.get("event_from_user", None)
        chat = data.get("event_chat", None)

        if user is None or getattr(user, "id", None) is None:
            return await handler(event, data)

        uid: int = int(user.id)
        if uid in self.admin_ids:
            return await handler(event, data)

        if self.private_only and chat is not None and getattr(chat, "type", None) != "private":
            return await handler(event, data)

        # حالة FSM الحالية (إن وُجدت)
        current_state: Optional[str] = None
        try:
            fsm = data.get("state")
            if fsm is not None:
                current_state = await fsm.get_state()  # مثل "report:collect"
        except Exception:
            current_state = None

        # (اختياري) معروف/مجهول
        if self.enforce_known_users:
            self._ensure_known_cache_fresh()
            if uid not in self._known_cache and not self._is_allowed_command(event):
                # اسمح للمجهول فقط إذا لديه نافذة إيصال مفتوحة
                if isinstance(event, Message):
                    ct = (event.content_type or "").lower()
                    try:
                        if _receipt_is_allowed(uid, ct):
                            pass  # نسمح بالمتابعة
                        else:
                            await self._notify_i18n(uid, event, unknown_user=True)
                            return None
                    except Exception:
                        await self._notify_i18n(uid, event, unknown_user=True)
                        return None
                else:
                    await self._notify_i18n(uid, event, unknown_user=True)
                    return None

        # --- تجاوز المنع أثناء FSM (للرسائل والكولباكات) ---
        if self.fsm_bypass and current_state:
            if not self.fsm_whitelist or current_state in self.fsm_whitelist:
                return await handler(event, data)
        # ----------------------------------------------------

        # منع الرسائل غير المعروفة (Messages فقط)
        if self.block_unknown_messages and isinstance(event, Message):
            if not self._passes_message_policy(event, current_state):
                await self._notify_i18n(uid, event, unknown_user=False)
                return None

        return await handler(event, data)

    # Helpers
    def _normalize_cmd(self, cmd: str) -> str:
        cmd = cmd.strip().lstrip("/")
        if "@" in cmd: cmd = cmd.split("@", 1)[0]
        if " " in cmd: cmd = cmd.split(" ", 1)[0]
        return cmd.lower()

    def _extract_text(self, event: TelegramObject) -> str:
        if isinstance(event, Message): return event.text or event.caption or ""
        if isinstance(event, CallbackQuery): return event.data or ""
        return ""

    def _is_allowed_command(self, event: TelegramObject) -> bool:
        text = (self._extract_text(event) or "").strip()
        if not text.startswith("/"): return False
        return self._normalize_cmd(text) in self.allow_commands

    def _passes_message_policy(self, m: Message, current_state: Optional[str]) -> bool:
        # 1) أوامر
        if m.text and m.text.strip().startswith("/"):
            return self._normalize_cmd(m.text) in self.allow_commands

        # 2) نوع الرسالة
        content_type = (m.content_type or "").lower()

        # ✅ 2.1 السماح المؤقت حسب نافذة الإيصال (photo/document/text)
        try:
            uid = m.from_user.id if m.from_user else None
            if uid and _receipt_is_allowed(int(uid), content_type):
                return True
        except Exception:
            pass

        # 2.2 السياسة العامة للأنواع
        if content_type not in self.allowed_content_types:
            return False

        # 3) نص حر
        text = (m.text or m.caption or "").strip()
        if content_type == "text":
            if self.allow_free_text:
                return True
            # ✅ السماح أثناء FSM state (قديمة)
            if current_state:
                if (self.state_whitelist is None) or (current_state in self.state_whitelist):
                    return True
            # Regexات مسموحة
            for pat in self.allow_text_regex:
                if pat.search(text or ""):
                    return True
            return False

        return True

    def _ensure_known_cache_fresh(self) -> None:
        now = time.time()
        if now - self._last_load_ts < self.cache_ttl:
            return
        self._known_cache = self._load_known_users()
        self._last_load_ts = now

    def _load_known_users(self) -> Set[int]:
        known: Set[int] = set()
        def _read(path: Path) -> None:
            try:
                if not path.exists(): return
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for x in data:
                        try: known.add(int(x))
                        except Exception: continue
                elif isinstance(data, dict):
                    for k in list(data.keys()):
                        try: known.add(int(k))
                        except Exception: continue
            except Exception as e:
                logger.error("[UnknownGate] Failed to read %s: %s", path, e)
        _read(self.known_users_file)
        for p in self.extra_hint_files: _read(Path(p))
        return known

    async def _notify_i18n(self, uid: Optional[int], event: TelegramObject, *, unknown_user: bool) -> None:
        lang = "en"
        try:
            if uid is not None: lang = get_user_lang(uid) or "en"
        except Exception:
            pass

        now = time.time()
        last = self._last_notified.get(uid or -1, 0.0)
        if now - last < self.notify_cooldown:
            return
        self._last_notified[uid or -1] = now

        if unknown_user:
            text = _tr(lang, self.i18n_key_unknown_user,
                       "⛔ This bot is restricted. Please send /start first.\n"
                       "⛔ هذا البوت مقيَّد. أرسل /start أولاً.")
        else:
            text = _tr(lang, self.i18n_key_unknown_msg,
                       "⛔ Unknown message. Only specific commands are allowed.\n"
                       "⛔ رسالة غير معروفة. يُسمح فقط بأوامر محددة.")

        try:
            if isinstance(event, Message):
                await event.answer(text, disable_web_page_preview=True)
            elif isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
        except Exception as e:
            logger.debug("[UnknownGate] notify failed: %s", e)
