#!/usr/bin/env bash
set -euo pipefail

# ====== ????? /data ? .env ======
mkdir -p /data
touch /data/.env
# ???? .env ?????? ??? ????? ??? ?? /data/.env ????
if [ -f ./.env ] && [ ! -s /data/.env ]; then cp ./.env /data/.env; fi
ln -sf /data/.env .env || true

# ????? BOT_TOKEN (?? ????? ?? Railway) ??? /data/.env
if [ -n "${BOT_TOKEN:-}" ]; then
  sed -i "/^BOT_TOKEN=/d" /data/.env || true
  printf "BOT_TOKEN=%s\n" "$BOT_TOKEN" >> /data/.env
fi

# ???? ??????? .env ??? ???? ???????
set -a
. ./.env || true
set +a

# ====== ????? MAINTENANCE ?? ??? ??????? ======
# MAINTENANCE=1  ???? /data/maintenance
# MAINTENANCE=0  ???? /data/maintenance
if [ "${MAINTENANCE:-0}" = "1" ]; then
  echo "[BOOT] maintenance=1  enabling maintenance flag"
  : > /data/maintenance
else
  echo "[BOOT] maintenance=0  clearing maintenance flag"
  rm -f /data/maintenance || true
fi

echo "[BOOT] BOT_TOKEN present? $([ -n "${BOT_TOKEN:-}" ] && echo yes || echo no)"

# ====== ???? ????? ????? ??? ??????? ======
while true; do
  if [ -f /data/maintenance ]; then
    echo "[BOOT] Maintenance ON  waiting"
    while [ -f /data/maintenance ]; do sleep 2; done
  fi

  echo "[BOOT] Starting bot"
  if /app/.venv/bin/python bot.py || python3 bot.py; then
    echo "[BOOT] Bot exited normally, restarting in 3s"
  else
    code=$?
    echo "[BOOT] Bot exited with code $code, restarting in 3s"
  fi
  sleep 3
done