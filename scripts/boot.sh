#!/usr/bin/env bash
set -euo pipefail

# ???? /data ? ???? .env
mkdir -p /data
touch /data/.env
ln -sf /data/.env .env || true

# 1) ???? .env ????? ???? ????????
set -a
. ./.env || true
set +a

# 2) ???? ??? Railway ???? /data/.env ??????? ??? ??????
override_var () {
  local key="$1" val="${2:-}"
  if [ -n "${val:-}" ]; then
    sed -i "/^${key}=*/d" /data/.env || true
    printf "%s=%s\n" "$key" "$val" >> /data/.env
  fi
}
override_var "BOT_TOKEN"   "${BOT_TOKEN:-}"
override_var "MAINTENANCE" "${MAINTENANCE:-}"
override_var "WIPE_DATA"   "${WIPE_DATA:-}"

# 3) ??? ??????? ??? ??????? ????? ????? ???????
set -a
. ./.env || true
set +a

echo "[BOOT] MAINTENANCE=${MAINTENANCE:-0} | WIPE_DATA=${WIPE_DATA:-0} | BOT_TOKEN? $([ -n "${BOT_TOKEN:-}" ] && echo yes || echo no)"

# WIPE_DATA: ???? ?? /data ????? .env
if [ "${WIPE_DATA:-0}" = "1" ]; then
  echo "[BOOT] wiping /data ..."
  find /data -mindepth 1 -maxdepth 1 ! -name ".env" -exec rm -rf {} +
  : > /data/shop_flags.json
  : > /data/shop_config.json
  : > /data/inv_blacklist.json
  rm -f /data/shop.db || true
  sed -i "/^WIPE_DATA=/d" /data/.env || true
  echo "WIPE_DATA=0" >> /data/.env
  echo "[BOOT] wipe done."
fi

# ?? ?????? ?? ????? ?????
if [ "${MAINTENANCE:-0}" = "1" ]; then
  echo "[BOOT] MAINTENANCE=1  not starting the bot."
  exec tail -f /dev/null
fi

# ???? ?????
exec /app/.venv/bin/python bot.py || exec python3 bot.py