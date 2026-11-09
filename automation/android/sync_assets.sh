#!/usr/bin/env bash
# Copy the complete game (www/) into the Android assets folder before Gradle runs.
# Same result as PR #2's syncGameAssets task, so this stays compatible after PR #2 merges.
# Fails if www/index.html or a required game file is missing.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$ROOT/www"
DST="$ROOT/android/app/src/main/assets"
REQ="$ROOT/automation/android/required_game_files.txt"

missing=0
while IFS= read -r f; do
  [[ -z "$f" || "$f" == \#* ]] && continue
  if [[ ! -f "$SRC/$f" ]]; then echo "::error::Required game file missing: www/$f"; missing=1; fi
done < "$REQ"
if [[ $missing -ne 0 ]]; then echo "Game sources incomplete; refusing to build an APK without the game." >&2; exit 1; fi

# Mirror (delete anything stale), then drop editor backups / OS junk.
rm -rf "$DST"
mkdir -p "$DST"
cp -a "$SRC/." "$DST/"
find "$DST" -type f \( -name 'index.*.bak.html' -o -name '.DS_Store' -o -name 'Thumbs.db' -o -name 'desktop.ini' \) -delete
count=$(find "$DST" -type f | wc -l)
echo "Synced www/ -> android/app/src/main/assets ($count files)"
