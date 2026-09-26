#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <desktop-build-directory> <appimagetool> <output.AppImage>" >&2
  exit 2
fi

source_dir="$(realpath "$1")"
appimagetool="$(realpath "$2")"
output="$(realpath -m "$3")"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ -x "$source_dir/FinancialBeancount" ]] || {
  echo "desktop executable is missing: $source_dir/FinancialBeancount" >&2
  exit 1
}
[[ -x "$appimagetool" ]] || {
  echo "appimagetool is missing or not executable: $appimagetool" >&2
  exit 1
}
[[ "$output" == *.AppImage ]] || {
  echo "output must use the .AppImage extension" >&2
  exit 1
}

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
appdir="$work_dir/FinancialBeancount.AppDir"
payload="$appdir/usr/lib/financial-beancount"
mkdir -p "$payload" "$appdir/usr/bin" "$appdir/usr/share/applications" \
  "$appdir/usr/share/icons/hicolor/scalable/apps" "$(dirname "$output")"
cp -a "$source_dir/." "$payload/"
cp "$script_dir/FinancialBeancount.desktop" \
  "$appdir/usr/share/applications/FinancialBeancount.desktop"
cp "$script_dir/financial-beancount.svg" \
  "$appdir/usr/share/icons/hicolor/scalable/apps/financial-beancount.svg"
ln -s usr/share/applications/FinancialBeancount.desktop "$appdir/FinancialBeancount.desktop"
ln -s usr/share/icons/hicolor/scalable/apps/financial-beancount.svg \
  "$appdir/financial-beancount.svg"
ln -s financial-beancount.svg "$appdir/.DirIcon"
ln -s ../lib/financial-beancount/FinancialBeancount "$appdir/usr/bin/FinancialBeancount"

cat > "$appdir/AppRun" <<'EOF'
#!/usr/bin/env bash
set -e
appdir="${APPDIR:-$(cd "$(dirname "$0")" && pwd)}"
exec "$appdir/usr/lib/financial-beancount/FinancialBeancount" "$@"
EOF
chmod 755 "$appdir/AppRun"

case "$(uname -m)" in
  x86_64|amd64) appimage_arch=x86_64 ;;
  aarch64|arm64) appimage_arch=aarch64 ;;
  *) echo "unsupported AppImage architecture: $(uname -m)" >&2; exit 1 ;;
esac

ARCH="$appimage_arch" "$appimagetool" "$appdir" "$output"
chmod 755 "$output"
