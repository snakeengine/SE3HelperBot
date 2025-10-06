#!/usr/bin/env bash
set -euo pipefail

# ====== ??? /data ? .env ======
mkdir -p /data
touch /data/.env
if [ -f ./.env ] && [ ! -s /data/.env ]; then cp ./.env /data/.env; fi
ln -sf /data/.env .env || true

# ??? .env
set -a
. ./.env || true
set +a

# ?????? BOT_TOKEN ?? ??????? ?????? ??? /data/.env (?? ???)
if [ -n "${BOT_TOKEN:-}" ]; then
  sed -i "/^BOT_TOKEN=/d" /data/.env || true
  printf "BOT_TOKEN=%s\n" "$BOT_TOKEN" >> /data/.env
fi

echo "[BOOT] MAINTENANCE=${MAINTENANCE:-0} | WIPE_DATA=${WIPE_DATA:-0} | BOT_TOKEN? $([ -n "${BOT_TOKEN:-}" ] && echo yes || echo no)"

# ====== WIPE_DATA: ??? ??? ????? /data ======
if [ "${WIPE_DATA:-0}" = "1" ]; then
  echo "[BOOT] WIPE_DATA=1  wiping /data ..."
  find /data -mindepth 1 -maxdepth 1 ! -name ".env" -exec rm -rf {} +
  : > /data/shop_flags.json
  : > /data/shop_config.json
  : > /data/inv_blacklist.json
  rm -f /data/shop.db || true
  sed -i "/^WIPE_DATA=/d" /data/.env || true
  echo "WIPE_DATA=0" >> /data/.env
  echo "[BOOT] wipe done."
fi

# ====== MAINTENANCE: ?? ???? ????? ======
if [ "${MAINTENANCE:-0}" = "1" ]; then
  echo "[BOOT] MAINTENANCE=1  not starting the bot."
  exec tail -f /dev/null
fi

# ====== ??? ????? ======
exec /app/.venv/bin/python bot.py || exec python3 bot.py