# handlers/__init__.py
from aiogram import Router

_loaded = False

def setup_handlers(dp):
    global _loaded
    if _loaded:
        return  # منع التكرار

    # استيراد كل الموديولات التي تعرّف router
    from . import help, about, supplier_vault, download, language, app_download
    from . import reseller, basic_cmds, contact, deviceinfo, version
    from . import verified_resellers, trusted_suppliers, security_status, safe_usage
    from . import deviceinfo_check, debug_callbacks
    # ... وأي handlers أخرى

    # ضمّ مرّة واحدة فقط
    dp.include_router(help.router)
    dp.include_router(about.router)
    dp.include_router(supplier_vault.router)
    # ... أكمل بقية الرواتر

    _loaded = True
