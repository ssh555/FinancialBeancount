# Release Gate and External Credentials

[English](RELEASE.md) | [简体中文](RELEASE.zh-CN.md)

The repository does not currently publish GitHub Releases. The desktop workflow produces reviewable
artifacts only; a successful workflow run is not permission to publish them.

The manually dispatched `release-candidate.yml` workflow is the only automated Release-creation
path. It requires an exact `vMAJOR.MINOR.PATCH` tag matching the source version, invokes all three
signed platform jobs, downloads their artifacts, rejects missing, duplicate or unexpected assets,
and creates a **draft** GitHub Release targeting the exact validated commit. It never publishes the
draft. The actual publisher must review the notes, asset inventory and signature results in GitHub
before manually publishing it.

## Ownership and documentation policy

Release identities belong to the actual publisher of a release. End users do not configure signing
certificates, timestamp services, Apple accounts or update-manifest keys. A downstream fork that
publishes binaries must use its own identities and must embed the public key corresponding to its own
update-manifest signing key. Private keys, certificate files and passwords must be stored only in
protected deployment secret stores; they must never be committed, printed in logs or bundled into the
application.

Every change to package formats, secret or variable names, signing/notarization commands, updater
asset names, supported upgrade versions or release gates must update this document and the relevant
README section in the same commit. Preview builds remain available without publisher credentials.
Requesting signed mode is fail-closed and never substitutes a test certificate or unsigned artifact.

### Publisher configuration matrix

| Scope | GitHub configuration | Owner | Status |
| --- | --- | --- | --- |
| Update manifest | Variable `FINANCIAL_BEANCOUNT_UPDATE_PUBLIC_KEY`; secret `FINANCIAL_BEANCOUNT_RELEASE_SIGNING_KEY` | Release publisher | Implemented; keys must be a matching Ed25519 pair |
| Windows | Secrets `FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE`, `FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE_PASSWORD`; variables `FINANCIAL_BEANCOUNT_WINDOWS_TIMESTAMP_URL`, `FINANCIAL_BEANCOUNT_WINDOWS_PUBLISHER` | Windows release publisher | Implemented; real certificate provisioning pending |
| macOS | Secrets `FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE`, `FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE_PASSWORD`, `FINANCIAL_BEANCOUNT_APPLE_ID`, `FINANCIAL_BEANCOUNT_APPLE_APP_PASSWORD`; variables `FINANCIAL_BEANCOUNT_MACOS_SIGNING_IDENTITY`, `FINANCIAL_BEANCOUNT_APPLE_TEAM_ID` | Apple Developer account holder | Implemented in workflow; clean-runner validation pending |
| Linux | Secret `FINANCIAL_BEANCOUNT_LINUX_SIGNING_KEY` and optional `FINANCIAL_BEANCOUNT_LINUX_SIGNING_KEY_PASSPHRASE`; variable `FINANCIAL_BEANCOUNT_LINUX_SIGNING_FINGERPRINT` | Linux release publisher | AppImage path implemented; real publisher-key validation pending |

Certificate renewal, revocation and operator handover are deployment operations. Before rotating any
identity, the publisher must verify the new trust chain in a preview/release-candidate run, update the
pinned public identity where applicable, preserve rollback access to the last trusted build, and
record the rotation in release notes. Revoked or expired credentials must never be bypassed by
disabling a gate.

## Implemented gates

- deterministic platform archives and SHA-256 manifests;
- Ed25519-signed update manifests with the public identity embedded in official builds;
- safe download, extraction, in-place replacement, health check and rollback;
- recoverable database migrations and a Windows/macOS/Linux upgrade matrix;
- privacy and offline-boundary tests.

The desktop workflow runs the fail-closed preview gate before uploading development artifacts. It
checks version consistency, required release documentation, the expected platform archive and its
exact SHA-256 manifest. The stricter publication gate additionally verifies the Ed25519 manifest
signature, a native installer and hash-bound evidence that the operating system signature was
successfully verified:

```bash
python scripts/release_gate.py --repository . --artifacts artifacts \
  --mode preview --platform windows --architecture X64
```

`--mode release` is enabled independently for every signed Windows, macOS and Linux job. Each job
must produce and verify its own native artifact before it can pass.

Platform verification evidence must be generated on the matching clean runner after signing. The
verifier pins the expected publisher or key fingerprint, rejects a non-zero native-tool result, and
binds its structured evidence to the installer name and SHA-256:

```bash
# Windows: trusted Authenticode chain, timestamp and expected publisher
python scripts/verify_platform_signature.py --platform windows \
  --installer artifacts/FinancialBeancount-windows-X64.msi \
  --expected-identity "<certificate publisher>"

# macOS: strict codesign verification plus Gatekeeper assessment
python scripts/verify_platform_signature.py --platform macos \
  --installer artifacts/FinancialBeancount-macos-ARM64.dmg \
  --expected-identity "<Developer ID identity>"

# Linux: detached signature verified by a dedicated release keyring
python scripts/verify_platform_signature.py --platform linux \
  --installer artifacts/FinancialBeancount-linux-X64.AppImage \
  --detached-signature artifacts/FinancialBeancount-linux-X64.AppImage.asc \
  --keyring release-keyring.gpg --expected-identity "<full signing fingerprint>"
```

The release gate rejects the earlier two-field self-reported JSON shape. Evidence now records its
schema, platform, artifact name, digest, pinned identity, native verifier and verification time.

## Complete private-ledger acceptance

Before a release candidate is approved, maintainers can import the complete private statement set,
promote only records that have no generated cross-source match candidate, export one portable file,
and restore that file into a fresh database for a table-by-table comparison:

```bash
python scripts/acceptance_full_ledger.py \
  --bills /path/to/private/statements \
  --output /path/to/new-empty-output-directory
```

The statement directory and generated databases/archive must remain outside Git (the repository's
`tmp/` directory is ignored and is suitable for local runs). Extracted supported statements are
processed independently; sibling ZIP originals are reported as skipped so they are not imported
twice. Unsupported or malformed content is named as unprocessed and prevents export. Ambiguous
match candidates remain pending for explicit review. A successful run emits
`complete-ledger.financial-beancount.zip` plus `acceptance-report.json`, then proves that the archive
can initialize the mobile ledger without loss.

## External credentials still required

These credentials must be obtained from their platform owners and stored only as protected GitHub
Actions secrets. Test or self-signed certificates do not satisfy the release gate.

- **Windows:** a trusted Authenticode code-signing certificate and private key. Sign and timestamp the
  main executable, updater helper and installer, then verify with Windows trust APIs on a clean runner.
- **macOS:** an Apple Developer ID Application certificate, App Store Connect notarization credentials
  and hardened-runtime entitlements. Sign the complete app bundle, notarize it, staple the ticket and
  verify with both `codesign` and Gatekeeper on a clean runner.
- **Linux:** a dedicated OpenPGP release-signing key. The full 40-character fingerprint is pinned as
  a repository variable; the base64 secret-key export and optional passphrase remain protected
  Actions secrets. Ed25519 update signatures protect portable archives independently.

## Publication blockers

A public Release must not be created until all applicable platform jobs produce an installer, verify
its operating-system signature on a clean runner, install over the previous supported version without
removing per-user data, and pass the release-upgrade and privacy gates. The CI job must fail closed when
credentials are missing, signatures are invalid, notarization fails or the installer requires an
uninstall/reinstall cycle.

Creating a draft candidate also requires `contents: write` for its final job. The signed build jobs
receive the protected platform secrets through the same-repository reusable workflow. Preview builds
and ordinary CI retain read-only contents permission. Re-running with an existing tag or draft fails
instead of overwriting release assets.

The cross-platform Ed25519 update manifest uses:

- repository variable `FINANCIAL_BEANCOUNT_UPDATE_PUBLIC_KEY`;
- Actions secret `FINANCIAL_BEANCOUNT_RELEASE_SIGNING_KEY`.

The signed Windows job additionally requires:

- Actions secret `FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE`: base64 PKCS#12 code-signing certificate;
- Actions secret `FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE_PASSWORD`;
- repository variable `FINANCIAL_BEANCOUNT_WINDOWS_TIMESTAMP_URL`: HTTPS RFC 3161 timestamp service;
- repository variable `FINANCIAL_BEANCOUNT_WINDOWS_PUBLISHER`: publisher text expected in trusted
  Authenticode verification output.

The workflow signs and immediately verifies `FinancialBeancount.exe` and
`FinancialBeancountUpdater.exe` before packaging, then signs the MSI, records native verification
evidence and runs the strict Windows Release gate. The temporary PKCS#12 file is deleted even on
failure. Missing credentials, malformed base64, signing failure, timestamp failure, untrusted chains
or publisher mismatch stop the job. GitHub-hosted runners are ephemeral, but organization policy
should still restrict these secrets to protected environments and approved release operators.

## Windows MSI preview

Unsigned development builds now produce a per-user MSI under
`%LOCALAPPDATA%\Programs\FinancialBeancount`. The package has a stable upgrade code and changing
product code, so a newer three-part version performs a Windows Installer major upgrade without an
uninstall/reinstall step. Application data remains separately under
`%LOCALAPPDATA%\FinancialBeancount`; neither upgrades nor uninstall author that directory for
removal.

The Windows CI job installs a generated `0.0.1` package, creates a user-data sentinel, upgrades in
place to the current package, and uninstalls it. It fails unless application files follow the
expected lifecycle while the sentinel survives both upgrade and uninstall. These MSI files remain
preview artifacts. With the protected configuration above, signed mode Authenticode-signs the
application, updater and MSI and must pass the strict native verification gate; this makes the
Windows artifact eligible for release review, but does not remove the macOS/Linux publication
blockers.

WiX validation remains enabled except for ICE38, ICE64 and ICE91 (which assume roaming or
machine-wide handling for files installed below a user profile) and ICE61 (which rejects the
intentional same-version preview rebuild path). The real install/upgrade/uninstall smoke test is the
required compensating gate for those narrowly documented suppressions; CI never uses global
validation suppression.

## macOS DMG preview

Unsigned macOS development builds now create a compressed read-only DMG containing the preserved
`FinancialBeancount.app` bundle and an `/Applications` symlink. The macOS CI job mounts the image
read-only, validates both entries, performs a replacement installation in a disposable Applications
directory, and proves that a ledger sentinel under the separate Application Support directory
survives replacement and application removal.

Signed mode imports a protected Developer ID Application certificate into a temporary keychain,
enables hardened runtime and secure timestamps, signs the application and DMG, waits for an explicit
`Accepted` result from `notarytool`, staples and validates the ticket, performs Gatekeeper assessment,
records native evidence and runs the strict macOS Release gate. It has no unsigned fallback.

The signed macOS job requires:

- Actions secret `FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE`: base64 PKCS#12 Developer ID certificate;
- Actions secret `FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE_PASSWORD`;
- repository variable `FINANCIAL_BEANCOUNT_MACOS_SIGNING_IDENTITY`;
- Actions secrets `FINANCIAL_BEANCOUNT_APPLE_ID` and
  `FINANCIAL_BEANCOUNT_APPLE_APP_PASSWORD`;
- repository variable `FINANCIAL_BEANCOUNT_APPLE_TEAM_ID`.

The temporary keychain and certificate are deleted on every exit. This path remains unverified until
it runs with the real credentials on a clean macOS runner.

## Linux AppImage

Linux builds use the official AppDir layout and SHA-256-pinned `appimagetool` 1.9.1 to create a
single AppImage. Installation is a user-owned file copy; upgrade atomically replaces that file and uninstall
removes only that file. CI extracts the image, checks its entry point and payload, replaces an
installed copy, removes it, and proves that a ledger sentinel in the separate user-data directory
survives throughout.

Signed mode imports the publisher key into a temporary GnuPG home, refuses a key whose full
fingerprint differs from `FINANCIAL_BEANCOUNT_LINUX_SIGNING_FINGERPRINT`, creates an armored detached
signature, exports a public verification keyring, verifies with `gpgv`, records hash-bound evidence,
and runs the strict Linux Release gate. The temporary secret-key home is deleted on every exit. A
positive run with the real publisher key remains required.
