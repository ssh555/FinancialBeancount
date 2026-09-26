#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <application.AppImage>" >&2
  exit 2
fi

appimage="$(realpath "$1")"
[[ -x "$appimage" ]] || { echo "AppImage is missing or not executable: $appimage" >&2; exit 1; }

work_dir="$(mktemp -d)"
data_home="$work_dir/data"
install_dir="$work_dir/bin"
trap 'rm -rf "$work_dir"' EXIT
mkdir -p "$data_home/FinancialBeancount" "$install_dir"
sentinel="$data_home/FinancialBeancount/ledger-preservation.sentinel"
printf '%s\n' 'ledger-must-survive' > "$sentinel"

# AppImage installation is a user-owned copy. Replacing that file is the in-place upgrade path.
cp "$appimage" "$install_dir/FinancialBeancount.AppImage"
chmod 755 "$install_dir/FinancialBeancount.AppImage"
cd "$work_dir"
"$install_dir/FinancialBeancount.AppImage" --appimage-extract >/dev/null
test -x squashfs-root/AppRun
test -x squashfs-root/usr/lib/financial-beancount/FinancialBeancount
rm -rf squashfs-root

replacement="$work_dir/replacement.AppImage"
cp "$appimage" "$replacement"
chmod 755 "$replacement"
mv -f "$replacement" "$install_dir/FinancialBeancount.AppImage"
test "$(cat "$sentinel")" = 'ledger-must-survive'

rm "$install_dir/FinancialBeancount.AppImage"
test "$(cat "$sentinel")" = 'ledger-must-survive'
