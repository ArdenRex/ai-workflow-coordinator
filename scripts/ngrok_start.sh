#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# scripts/ngrok_start.sh
# Starts FastAPI + ngrok and prints the Slack Events Request URL.
#
# Usage:
#   chmod +x scripts/ngrok_start.sh
#   ./scripts/ngrok_start.sh
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

PORT=8000
NGROK_WAIT=8   # seconds to wait for ngrok tunnel to be ready
MAX_RETRIES=5

echo "▶ Starting FastAPI server on port $PORT..."
uvicorn app.main:app --reload --port "$PORT" &
SERVER_PID=$!
sleep 2

# Verify server started
if ! kill -0 "$SERVER_PID" 2>/dev/null; then
  echo "❌ FastAPI server failed to start. Check the logs above."
  exit 1
fi

echo "▶ Starting ngrok tunnel..."
ngrok http "$PORT" --log=stdout &
NGROK_PID=$!

echo "⏳ Waiting ${NGROK_WAIT}s for ngrok tunnel..."
sleep "$NGROK_WAIT"

# Retry fetching the public URL
PUBLIC_URL=""
for i in $(seq 1 $MAX_RETRIES); do
  PUBLIC_URL=$(curl -s http://localhost:4040/api/tunnels \
    | python3 -c "
import sys, json
try:
    t = json.load(sys.stdin).get('tunnels', [])
    https = [x['public_url'] for x in t if x['proto'] == 'https']
    print(https[0] if https else '')
except Exception:
    print('')
" 2>/dev/null)
  if [ -n "$PUBLIC_URL" ]; then
    break
  fi
  echo "  Retry $i/$MAX_RETRIES — ngrok not ready yet..."
  sleep 2
done

if [ -z "$PUBLIC_URL" ]; then
  echo ""
  echo "❌ Could not retrieve ngrok public URL."
  echo "   Is ngrok installed and authenticated? Run: ngrok config check"
  kill "$SERVER_PID" "$NGROK_PID" 2>/dev/null || true
  exit 1
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  Paste this URL into your Slack App dashboard:"
echo ""
echo "  ${PUBLIC_URL}/slack/events"
echo ""
echo "  https://api.slack.com/apps → Event Subscriptions → Request URL"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "  Press Ctrl+C to stop both servers."

# Cleanup on exit
trap 'echo ""; echo "Stopping..."; kill "$SERVER_PID" "$NGROK_PID" 2>/dev/null || true' EXIT INT TERM

wait "$SERVER_PID" "$NGROK_PID"
