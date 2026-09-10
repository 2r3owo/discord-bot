#!/bin/sh
set -e

echo "🔐 bgutil PO Token 서버 시작..."
/usr/bin/deno run \
  --allow-env \
  --allow-net \
  --allow-ffi=/app/node_modules \
  --allow-read=/app/node_modules \
  /app/src/main.ts \
  --host 127.0.0.1 \
  --port 4416 &

POT_PID=$!

cleanup() {
  kill "$POT_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

sleep 2

echo "🎵 Discord 봇 시작..."
exec /opt/venv/bin/python /bot/main.py
