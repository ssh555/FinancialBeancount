#!/bin/bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: smoke_dmg.sh DMG" >&2
  exit 2
fi

dmg="$1"
if [[ ! -f "$dmg" ]]; then
  echo "DMG does not exist: $dmg" >&2
  exit 2
fi

workspace="$(mktemp -d "${TMPDIR:-/tmp}/financial-beancount-dmg-smoke.XXXXXX")"
mountpoint="$workspace/mount"
applications="$workspace/Applications"
user_data="$workspace/Library/Application Support/FinancialBeancount"
sentinel="$user_data/ledger-sentinel.txt"
mounted=false
cleanup() {
  if [[ "$mounted" == true ]]; then
    hdiutil detach "$mountpoint" -quiet || true
  fi
  rm -rf "$workspace"
}
trap cleanup EXIT

mkdir -p "$mountpoint" "$applications" "$user_data"
printf '%s' 'preserve-user-ledger' > "$sentinel"
hdiutil attach "$dmg" -mountpoint "$mountpoint" -nobrowse -readonly -quiet
mounted=true

test -d "$mountpoint/FinancialBeancount.app"
test -L "$mountpoint/Applications"
test "$(readlink "$mountpoint/Applications")" = "/Applications"

ditto "$mountpoint/FinancialBeancount.app" "$applications/FinancialBeancount.app"
test -x "$applications/FinancialBeancount.app/Contents/MacOS/FinancialBeancount"

# A drag-to-Applications update replaces only the application bundle. The ledger lives elsewhere.
rm -rf "$applications/FinancialBeancount.app"
ditto "$mountpoint/FinancialBeancount.app" "$applications/FinancialBeancount.app"
test "$(cat "$sentinel")" = "preserve-user-ledger"

rm -rf "$applications/FinancialBeancount.app"
test "$(cat "$sentinel")" = "preserve-user-ledger"
echo "macOS DMG mount, replacement upgrade, uninstall and data preservation smoke passed."
