# Release Gate and External Credentials

The repository does not currently publish GitHub Releases. The desktop workflow produces reviewable
artifacts only; a successful workflow run is not permission to publish them.

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

`--mode release` is intentionally not enabled in the workflow yet: it must fail until the native
installer and platform-signature stages described below exist.

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
- **Linux:** a selected distributable installer/package format and its repository or package-signing
  identity. The Ed25519 update signature protects portable archives but does not replace distribution
  package signing.

## Publication blockers

A public Release must not be created until all applicable platform jobs produce an installer, verify
its operating-system signature on a clean runner, install over the previous supported version without
removing per-user data, and pass the release-upgrade and privacy gates. The CI job must fail closed when
credentials are missing, signatures are invalid, notarization fails or the installer requires an
uninstall/reinstall cycle.

The following existing GitHub configuration is only for the cross-platform Ed25519 update manifest:

- repository variable `FINANCIAL_BEANCOUNT_UPDATE_PUBLIC_KEY`;
- Actions secret `FINANCIAL_BEANCOUNT_RELEASE_SIGNING_KEY`.

Platform certificate secret names will be added together with their installer implementation, so no
unused long-lived certificate material needs to be provisioned early.
