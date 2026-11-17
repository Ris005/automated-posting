#!/usr/bin/env bash
# Demo the whole flow without any real API keys:
#  - Discord, Mastodon, Bluesky  -> a local fake API (scripts/mock_platforms.py) -> SUCCESS
#  - Telegram, DEV, GitHub, Pastebin -> the REAL APIs with fake keys -> real auth errors (FAILED)
# Shows that one platform failing never stops the others.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}

$PY scripts/mock_platforms.py & MOCK=$!
env -i PATH="$PATH" HOME="$HOME" \
  MASTODON_BASE_URL=http://127.0.0.1:4100 MASTODON_ACCESS_TOKEN=good-mastodon \
  BLUESKY_SERVICE_URL=http://127.0.0.1:4100 BLUESKY_HANDLE=me.test BLUESKY_APP_PASSWORD=pw \
  DISCORD_WEBHOOK_URL=http://127.0.0.1:4100/api/webhooks/1/tok \
  TELEGRAM_BOT_TOKEN=123:fake TELEGRAM_CHAT_ID=@nochannel \
  GITHUB_TOKEN=ghp_fake DEVTO_API_KEY=fake PASTEBIN_API_KEY=fake LOG_FILE=logs/demo.log \
  $PY -m uvicorn app.main:app --port 4000 > /dev/null 2>&1 & SRV=$!
trap 'kill $SRV $MOCK 2>/dev/null' EXIT

for _ in $(seq 30); do curl -s localhost:4000/health > /dev/null && break; sleep 0.5; done

echo "== POST /posting (valid message)"
curl -s -X POST localhost:4000/posting -H 'Content-Type: application/json' \
  -d '{"message":"Grow your online visibility today https://example.com"}' | $PY -m json.tool
echo
echo "== POST /posting (two links -> 422)"
curl -s -X POST localhost:4000/posting -H 'Content-Type: application/json' \
  -d '{"message":"Visit https://a.com and https://b.com"}'
echo
