#!/usr/bin/env bash
# Build the site, then serve it at http://localhost:8000 until you press Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")"
./build.sh
echo "Serving http://localhost:8000"
exec python3 -m http.server 8000 --bind 127.0.0.1
