#!/bin/sh

set -eu

PORT="${PORT:-8080}"

echo "======================================"
echo " Starting Mirror Server"
echo " Port: ${PORT}"
echo "======================================"

gunicorn \
    --bind "0.0.0.0:${PORT}" \
    --workers 2 \
    --threads 4 \
    --timeout 0 \
    app:app &

APP_PID=$!

sleep 3

rm -f /tmp/cloudflared.log

echo "Starting Cloudflare Quick Tunnel..."

cloudflared tunnel \
    --no-autoupdate \
    --url "http://127.0.0.1:${PORT}" \
    2>&1 | tee /tmp/cloudflared.log &

CF_PID=$!

echo "Waiting for Cloudflare URL..."

CF_URL=""

for i in $(seq 1 60); do

    CF_URL=$(grep -oE \
        'https://[-a-zA-Z0-9]+\.trycloudflare\.com' \
        /tmp/cloudflared.log 2>/dev/null |
        head -n 1 || true)

    if [ -n "$CF_URL" ]; then
        break
    fi

    sleep 1
done

echo ""

if [ -n "$CF_URL" ]; then
    echo "======================================"
    echo " CLOUDFLARE QUICK TUNNEL READY"
    echo " $CF_URL"
    echo "======================================"
else
    echo "Cloudflare URL not detected yet."
fi

echo ""

wait "$APP_PID"
