#!/bin/bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: build_dmg.sh APP_BUNDLE OUTPUT_DMG" >&2
  exit 2
fi

app_bundle="$1"
output_dmg="$2"
if [[ ! -d "$app_bundle" || "$(basename "$app_bundle")" != "FinancialBeancount.app" ]]; then
  echo "FinancialBeancount.app bundle does not exist: $app_bundle" >&2
  exit 2
fi
if [[ -e "$output_dmg" ]]; then
  echo "output already exists: $output_dmg" >&2
  exit 2
fi

mkdir -p "$(dirname "$output_dmg")"
staging="$(mktemp -d "${TMPDIR:-/tmp}/financial-beancount-dmg.XXXXXX")"
cleanup() {
  rm -rf "$staging"
}
trap cleanup EXIT

ditto "$app_bundle" "$staging/FinancialBeancount.app"
ln -s /Applications "$staging/Applications"
hdiutil create \
  -srcfolder "$staging" \
  -volname "FinancialBeancount" \
  -format UDZO \
  -ov \
  "$output_dmg"
test -s "$output_dmg"
