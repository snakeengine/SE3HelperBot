#!/usr/bin/env bash
set -euo pipefail

# ====== ????? /data ? .env ======
mkdir -p /data
touch /data/.env
if [ -f ./.env ] && [ ! -s /data/.env ]; then cp ./.env /data/.env; fi
ln -sf /data/.env .env || true

# ====== ???? ?????? ?????? ??? /data/.env ??? ??????? ======
sync_env_key() {
  local key="$1"; local val="${2:-}"
  if [ -n "$val" ]; then
    sed -i "/^${key}=*/d" /data/.env 2>/dev/null || true
    printf "%s=%s\n" "$key" "$val" >> /data/.env
  fi
}
sync_env_key "BOT_TOKEN"    "${BOT_TOKEN:-}"
sync_env_key "MAINTENANCE"  "${MAINTENANCE:-}"

# ???? ??????? .env
set -a
. ./.env || true
set +a

echo "[BOOT] MAINTENANCE=${MAINTENANCE:-unset}"
echo "[BOOT] BOT_TOKEN present? $([ -n "${BOT_TOKEN:-}" ] && echo yes || echo no)"

# ====== ???? ??? ??????? ======
if [ "${MAINTENANCE:-0}" = "1" ]; then
  echo "[BOOT] maintenance=1  enabling maintenance flag"
  : > /data/maintenance
else
  echo "[BOOT] maintenance=0  clearing maintenance flag"
  rm -f /data/maintenance || true
fi

# ====== ???? ??????? ======
while true; do
  if [ -f /data/maintenance ]; then
    echo "[BOOT] Maintenance ON  waiting"
    while [ -f /data/maintenance ]; do sleep 2; done
  fi

  echo "[BOOT] Starting bot"
  /app/.venv/bin/python bot.py || python3 bot.py
  echo "[BOOT] Bot exited, restarting in 3s"
  sleep 3
done