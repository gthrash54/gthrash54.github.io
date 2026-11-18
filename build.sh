#!/usr/bin/env bash
# Build the site and check it. Never runs git: review with `git status` and `git diff`, then commit yourself.
set -euo pipefail
cd "$(dirname "$0")"

# Refresh cv.pdf from the path in site.json when that copy is newer or different.
cv_pdf=$(python3 -c 'import json, os; print(os.path.expanduser(json.load(open("site.json"))["cv_pdf"]))')
if [ -f "$cv_pdf" ]; then
  cmp -s "$cv_pdf" cv.pdf || { cp "$cv_pdf" cv.pdf; echo "updated cv.pdf"; }
else
  echo "warning: $cv_pdf not found; cv.pdf left as is" >&2
fi

python3 -m unittest discover -s tests -q
python3 build.py
python3 tools/check-site.py
