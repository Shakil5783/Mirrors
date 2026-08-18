#!/bin/sh

set -eu

PORT="${PORT:-8080}"

echo "======================================"
echo " Starting File Mirror Server"
echo " Port: $PORT"
echo "======================================"

python3 app.py &
APP_PID=$!

sleep 3

echo "Starting Cloudflare Quick Tunnel..."

cloudflared tunnel \
    --no-autoupdate \
    --url "http://127.0.0.1:${PORT}" \
    2>&1 | tee /tmp/cloudflared.log &
CF_PID=$!

sleep 5

CF_URL=$(grep -oE 'https://[-a-zA-Z0-9]+\.trycloudflare\.com' /tmp/cloudflared.log | head -n 1 || true)

if [ -n "$CF_URL" ]; then
    echo ""
    echo "======================================"
    echo " CLOUDFLARE QUICK TUNNEL"
    echo " $CF_URL"
    echo "======================================"
    echo ""
else
    echo "Cloudflare URL not detected yet."
    echo "Check /tmp/cloudflared.log"
fi

wait $APP_PID
