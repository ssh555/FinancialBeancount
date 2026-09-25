#!/bin/bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: sign_and_notarize.sh APP_BUNDLE OUTPUT_DMG" >&2
  exit 2
fi

app_bundle="$1"
output_dmg="$2"
: "${FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE:?base64 PKCS#12 certificate is required}"
: "${FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE_PASSWORD:?certificate password is required}"
: "${FINANCIAL_BEANCOUNT_MACOS_SIGNING_IDENTITY:?Developer ID Application identity is required}"
: "${FINANCIAL_BEANCOUNT_APPLE_ID:?Apple ID is required}"
: "${FINANCIAL_BEANCOUNT_APPLE_APP_PASSWORD:?Apple app-specific password is required}"
: "${FINANCIAL_BEANCOUNT_APPLE_TEAM_ID:?Apple Developer team ID is required}"

if [[ ! -d "$app_bundle" || "$(basename "$app_bundle")" != "FinancialBeancount.app" ]]; then
  echo "FinancialBeancount.app bundle does not exist: $app_bundle" >&2
  exit 2
fi
if [[ -e "$output_dmg" ]]; then
  echo "output already exists: $output_dmg" >&2
  exit 2
fi

signing_root="$(mktemp -d "${TMPDIR:-/tmp}/financial-beancount-signing.XXXXXX")"
keychain="$signing_root/release.keychain-db"
certificate="$signing_root/developer-id.p12"
keychain_password="$(openssl rand -hex 24)"
cleanup() {
  security delete-keychain "$keychain" >/dev/null 2>&1 || true
  rm -rf "$signing_root"
}
trap cleanup EXIT

printf '%s' "$FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE" | base64 -D > "$certificate"
security create-keychain -p "$keychain_password" "$keychain"
security set-keychain-settings -lut 21600 "$keychain"
security unlock-keychain -p "$keychain_password" "$keychain"
security import "$certificate" \
  -k "$keychain" \
  -P "$FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE_PASSWORD" \
  -T /usr/bin/codesign
security set-key-partition-list \
  -S apple-tool:,apple:,codesign: \
  -s -k "$keychain_password" "$keychain"

codesign \
  --force \
  --deep \
  --options runtime \
  --timestamp \
  --keychain "$keychain" \
  --sign "$FINANCIAL_BEANCOUNT_MACOS_SIGNING_IDENTITY" \
  "$app_bundle"
codesign --verify --deep --strict --verbose=2 "$app_bundle"

bash "$(dirname "$0")/build_dmg.sh" "$app_bundle" "$output_dmg"
codesign \
  --force \
  --timestamp \
  --keychain "$keychain" \
  --sign "$FINANCIAL_BEANCOUNT_MACOS_SIGNING_IDENTITY" \
  "$output_dmg"
codesign --verify --strict --verbose=2 "$output_dmg"

notary_result="$signing_root/notary-result.json"
xcrun notarytool submit "$output_dmg" \
  --apple-id "$FINANCIAL_BEANCOUNT_APPLE_ID" \
  --password "$FINANCIAL_BEANCOUNT_APPLE_APP_PASSWORD" \
  --team-id "$FINANCIAL_BEANCOUNT_APPLE_TEAM_ID" \
  --wait \
  --output-format json > "$notary_result"
python3 - "$notary_result" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("status") != "Accepted":
    raise SystemExit(f"notarization was not accepted: {payload.get('status', 'missing status')}")
PY

xcrun stapler staple -v "$output_dmg"
xcrun stapler validate -v "$output_dmg"
spctl --assess --type open --verbose=4 "$output_dmg"
