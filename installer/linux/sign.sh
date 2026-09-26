#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <application.AppImage> <expected-full-fingerprint> <output-keyring.gpg>" >&2
  exit 2
fi

appimage="$(realpath "$1")"
expected="$(printf '%s' "$2" | tr -d '[:space:]' | tr '[:lower:]' '[:upper:]')"
keyring="$(realpath -m "$3")"
secret_key="${FINANCIAL_BEANCOUNT_LINUX_SIGNING_KEY:-}"
passphrase="${FINANCIAL_BEANCOUNT_LINUX_SIGNING_KEY_PASSPHRASE:-}"
[[ -f "$appimage" ]] || { echo "AppImage does not exist: $appimage" >&2; exit 1; }
[[ "$expected" =~ ^[0-9A-F]{40}$ ]] || { echo "expected fingerprint must contain 40 hexadecimal characters" >&2; exit 1; }
[[ -n "$secret_key" ]] || { echo "FINANCIAL_BEANCOUNT_LINUX_SIGNING_KEY is required" >&2; exit 1; }

gnupg_home="$(mktemp -d)"
key_file="$gnupg_home/release-key.asc"
trap 'rm -rf "$gnupg_home"' EXIT
chmod 700 "$gnupg_home"
printf '%s' "$secret_key" | base64 --decode > "$key_file"
GNUPGHOME="$gnupg_home" gpg --batch --import "$key_file" >/dev/null
actual="$(GNUPGHOME="$gnupg_home" gpg --batch --with-colons --list-secret-keys | awk -F: '$1 == "fpr" { print toupper($10); exit }')"
[[ "$actual" == "$expected" ]] || { echo "imported signing key fingerprint does not match the expected fingerprint" >&2; exit 1; }

signature="$appimage.asc"
if [[ -n "$passphrase" ]]; then
  printf '%s' "$passphrase" | GNUPGHOME="$gnupg_home" gpg --batch --yes \
    --pinentry-mode loopback --passphrase-fd 0 --local-user "$expected" \
    --armor --detach-sign --output "$signature" "$appimage"
else
  GNUPGHOME="$gnupg_home" gpg --batch --yes --local-user "$expected" \
    --armor --detach-sign --output "$signature" "$appimage"
fi
mkdir -p "$(dirname "$keyring")"
GNUPGHOME="$gnupg_home" gpg --batch --export "$expected" > "$keyring"
gpgv --keyring "$keyring" "$signature" "$appimage"
