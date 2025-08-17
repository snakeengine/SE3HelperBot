# handlers/__init__.py
from importlib import import_module

# كل الملفات المحتملة داخل handlers
_MODULES = [
    "language_command",
    "start", "help", "about", "download",
    "language_handlers", "language",
    "unknown", "contact", "deviceinfo", "version", "reseller",
    "security_status", "safe_usage", "deviceinfo_check",
    "server_status", "report", "tools_handler", "debug_callbacks",
]

__all__ = []

for name in _MODULES:
    try:
        mod = import_module(f".{name}", __name__)
        globals()[name] = mod
        __all__.append(name)
    except Exception:
        # لو ملف ناقص، نتخطّاه بدون ما نكسر الاستيراد
        pass
