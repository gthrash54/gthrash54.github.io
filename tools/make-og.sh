#!/usr/bin/env bash
# Render tools/og-card.html to og.png (1200x630) with headless Chrome or Chromium.
# Run by hand after editing the card; build.sh does not run it.
set -euo pipefail
cd "$(dirname "$0")/.."
browser=$(command -v chromium || command -v google-chrome-stable || command -v google-chrome) \
  || { echo "make-og.sh: needs chromium or google-chrome" >&2; exit 1; }
"$browser" --headless=new --disable-gpu --hide-scrollbars --window-size=1200,630 \
  --virtual-time-budget=5000 --screenshot="$PWD/og.png" "file://$PWD/tools/og-card.html" 2>/dev/null
echo "wrote og.png"
