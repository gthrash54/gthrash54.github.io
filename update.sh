#!/usr/bin/env bash
# Publish the site: refresh the CV PDF from Dropbox, commit everything, push.
set -euo pipefail
cd "$(dirname "$0")"
# Regenerate the peer-reviewed list from the Zotero-exported bib (same source as the LaTeX CV).
./build-publications.py
if [ -f "$HOME/Dropbox/CV/CV_GWT.pdf" ]; then cp "$HOME/Dropbox/CV/CV_GWT.pdf" cv.pdf; fi
git add -A
if git diff --cached --quiet; then echo "Nothing changed."; exit 0; fi
git commit -q -m "Update site $(date +%Y-%m-%d)"
git push -q origin main
echo "Pushed. Live at https://garrettthrash.com in about a minute."
