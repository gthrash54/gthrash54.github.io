#!/usr/bin/env bash
# Build and check the site, build the preview (writing drafts and drafts/commonplace/ included) into
# drafts/_site, then serve it over the repository at http://localhost:8000 until you press Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")"
./build.sh
python3 build.py --preview
exec python3 tools/serve.py 8000
