#!/usr/bin/env bash
# CI Android build for Project Aussie (debug test APK, package com.barrarun.game.ci).
# Usage: automation/android/ci_build.sh [output-dir]
# Env: ANDROID_HOME (SDK), JAVA_HOME (JDK 17). Optional GRADLE_CMD to override ./gradlew.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:-$ROOT/ci-out}"
mkdir -p "$OUT"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# 1. Throwaway debug keystore, created fresh for this job and never committed.
KS="$WORK/ci-debug.keystore"
PASS="$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 20)"
if [[ -n "${GITHUB_ACTIONS:-}" ]]; then echo "::add-mask::$PASS"; fi
keytool -genkeypair -noprompt -keystore "$KS" -storetype PKCS12 -storepass "$PASS" -keypass "$PASS" \
  -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 30 \
  -dname "CN=Project Aussie CI throwaway, O=CI, C=AU" >/dev/null 2>&1
export CI_DEBUG_KEYSTORE="$KS" CI_DEBUG_KEYSTORE_PASSWORD="$PASS" CI_DEBUG_KEY_ALIAS=androiddebugkey

# 2. Put the complete game into the Android assets folder.
"$ROOT/automation/android/sync_assets.sh"

# 3. Build with the CI init script (signing + .ci suffix injected; build.gradle untouched).
cd "$ROOT/android"
[[ -f local.properties ]] || echo "sdk.dir=${ANDROID_HOME:?ANDROID_HOME not set}" > local.properties
GRADLE_CMD="${GRADLE_CMD:-./gradlew}"
$GRADLE_CMD --no-daemon --stacktrace -I "$ROOT/automation/android/ci-init.gradle" assembleDebug

# 4. Verify the APK really contains the game and has the CI package id.
APK="$(ls "$ROOT"/android/app/build/outputs/apk/debug/*.apk | head -1)"
SHA="$(sha256sum "$APK" | cut -d' ' -f1)"
NAME="ProjectAussie-ci-$(git -C "$ROOT" rev-parse --short HEAD).apk"
cp "$APK" "$OUT/$NAME"
python3 "$ROOT/automation/android/verify_apk.py" "$OUT/$NAME" --www "$ROOT/www" \
  --expect-package com.barrarun.game.ci --json "$OUT/apk-verify.json"
echo "$SHA  $NAME" > "$OUT/$NAME.sha256"
echo "APK: $OUT/$NAME ($(stat -c %s "$OUT/$NAME") bytes, sha256 $SHA)"
