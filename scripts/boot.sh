#!/usr/bin/env bash
set -e

# تأكد من وجود مجلد البيانات
mkdir -p /data

# امسح أعلام/ملفات وضع الصيانة إن وجدت
rm -f /data/.feature_flags.lock /data/maintenance /data/.maintenance || true

# ضمن وجود ملف .env تحت /data واربطه
touch /data/.env
if [ -f .env ] && [ ! -s /data/.env ]; then cp .env /data/.env; fi
ln -sf /data/.env .env || true

# افرض MAINTENANCE=0 داخل /data/.env
if grep -q '^MAINTENANCE=' /data/.env 2>/dev/null; then
  sed -i 's/^MAINTENANCE=.*/MAINTENANCE=0/' /data/.env || true
else
  printf '\nMAINTENANCE=0\n' >> /data/.env
fi

# شغل البوت
exec /app/.venv/bin/python bot.py || exec python3 bot.py
