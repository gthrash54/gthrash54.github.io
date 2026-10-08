#!/usr/bin/env bash
# Publish the site: refresh the CV PDF from Dropbox, commit everything, push.
set -euo pipefail
cd "$(dirname "$0")"
# Regenerate the peer-reviewed list from the Zotero-exported bib (same source as the LaTeX CV).
./build-publications.py
if [ -f "$HOME/Dropbox/CV/CV_GWT.pdf" ]; then cp "$HOME/Dropbox/CV/CV_GWT.pdf" cv.pdf; fi
# Warn when the landing page's "Now" strip is older than 90 days.
if now_line=$(grep -o 'Now · [A-Za-z]* [0-9]\{4\}' index.html | head -1); then
  now_ts=$(date -d "1 ${now_line#Now · }" +%s 2>/dev/null || echo 0)
  if [ $(( $(date +%s) - now_ts )) -gt $((90*86400)) ]; then echo "WARNING: the Now strip on index.html says '${now_line#Now · }'; update it." >&2; fi
fi
git add -A
if git diff --cached --quiet; then echo "Nothing changed."; exit 0; fi
git commit -q -m "Update site $(date +%Y-%m-%d)"
git push -q origin main
echo "Pushed. Live at https://garrettthrash.com in about a minute."
