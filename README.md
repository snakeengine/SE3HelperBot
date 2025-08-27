# SnakeEngine Alerts System

**آخر تحديث:** 2025-08-26T12:38:49.713470Z

## الملفات
- `handlers/alerts_user.py` — أوامر المستخدم: `/alerts_on`, `/alerts_off`, `/alerts_status`
- `admin/alerts_admin.py` — لوحة الأدمن: تعديل/معاينة/إرسال/جدولة/إحصائيات
- `utils/alerts_broadcast.py` — البث + ساعات الهدوء + الحد الأسبوعي + Rate limit
- `utils/alerts_scheduler.py` — طابور وجدولة الإرسال
- `lang/locales/en.alerts.json`, `lang/locales/ar.alerts.json` — مفاتيح الترجمة المقترحة
- `.env.example` — متغيرات اختيارية

## دمج سريع مع bot.py
```python
from admin.alerts_admin import router as alerts_admin_router
from handlers.alerts_user import router as alerts_user_router
from utils.alerts_scheduler import init_alerts_scheduler

dp.include_router(alerts_user_router)
dp.include_router(alerts_admin_router)

from aiogram import Bot
async def _on_startup(bot: Bot):
    await init_alerts_scheduler(bot)

dp.startup.register(_on_startup)
```

## أوامر الأدمن
- `/push_update` — فتح لوحة التحكم (تحرير/معاينة/إرسال/جدولة/إحصائيات)`
