#!/usr/bin/env bash
# Fails if anything that looks like a provider API key appears in client code (web app or iOS app).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PATTERN='(sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9]{32,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|xi-api-key|Ocp-Apim-Subscription-Key)'
if grep -RInE "$PATTERN" "$ROOT/ios" "$ROOT/web" --include='*.swift' --include='*.plist' --include='*.json' \
     --include='*.xcconfig' --include='*.yml' --include='*.js' --include='*.html' --include='*.webmanifest'; then
  echo "❌ Possible API key found in client code. Keys must stay on the backend." >&2
  exit 1
fi
echo "✅ No provider API keys found in client code (web + iOS)."
