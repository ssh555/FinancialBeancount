# FinancialBeancount Roadmap

[English](ROADMAP.md) | [简体中文](ROADMAP.zh-CN.md)

This roadmap records release gates that must not be lost while implementation proceeds in small,
auditable stages. It does not imply that a release should be created early.

## Current delivery track

- Local-first responsive web application bundled with the ledger engine.
- Desktop controller and reproducible Windows, macOS, and Linux application builds.
- Android packaging only after the ledger engine can run fully offline inside the application.

## Release gate: updates without uninstalling

Before the first downloadable Release is published, implement and verify an update path that does
not require users to uninstall and reinstall the application:

- Preserve the per-user ledger database and configuration across application upgrades.
- Use forward-only, tested schema migrations with a backup taken before migration.
- Publish signed/versioned artifacts and verify update metadata and downloaded artifact hashes.
- Support an in-application update check with explicit user consent before download/install.
- Use the GitHub Releases API for `ssh555/FinancialBeancount` as the default update metadata source;
  allow advanced users and downstream builds to override or disable that source.
- Match assets by operating system and CPU architecture, and never download an incompatible build.
- Show the version, release notes, download size, and publishing identity before asking the user to
  approve an update.
- After approval, download the GitHub Release asset to a staging directory, verify its published
  checksum and platform signature, then invoke an in-place platform installer or a small updater
  helper after the application exits.
- Treat GitHub API/network failures as non-fatal: the ledger must keep working fully offline, and
  update checks must use timeouts, rate-limit awareness, and a user-controlled check frequency.
- Prefer differential updates where the target platform supports them; otherwise use an in-place
  installer upgrade that retains user data.
- Define rollback behavior for application binaries without silently downgrading the ledger schema.
- Test upgrades from every supported released version on Windows, macOS, Linux, and Android.
- Document offline/manual update installation for devices that never connect to the internet.

Release creation remains intentionally deferred until GUI packaging, update behavior, privacy
review, and end-to-end tests are complete.

### Implemented foundation

- The desktop controller exposes a user-triggered update check; no background request, download, or
  installation occurs without an explicit confirmation at the corresponding step.
- Stable release metadata is validated, draft/prerelease entries are ignored, and the update must
  provide both a matching platform/architecture ZIP and its SHA-256 asset.
- The default GitHub API source can be disabled or replaced by an HTTPS endpoint through
  `FINANCIAL_BEANCOUNT_UPDATE_API`.
- CI produces version-ready platform/architecture ZIP assets and adjacent SHA-256 manifests.
- Signed-release CI creates an Ed25519 signature for each exact SHA-256 manifest from a GitHub
  Actions secret. The application embeds only the corresponding public key and rejects missing,
  malformed, tampered, or mismatched signatures before downloading an archive. Unsigned development
  artifacts cannot enter the automatic update path.
- Approved downloads stream into a per-user staging directory, enforce declared and maximum sizes,
  verify the published SHA-256, and reject unsafe ZIP paths, symbolic links, and decompression bombs.
- A separately packaged helper waits for the running application to exit, retains the previous
  binaries, swaps the prepared application in place, and starts it. The replacement must report
  local-server readiness through a one-time health marker; otherwise the helper restores the old
  version. CI exercises the packaged helper against disposable directories.
- The controller probes installation and parent-directory permissions before exit. Protected Windows
  installs can use an explicit UAC prompt; refusal or launch failure keeps the current process and
  ledger untouched, while other platforms receive a verified manual-replacement path. A late helper
  failure restores/restarts the retained application and writes a local diagnostic.
- A required Windows/macOS/Linux CI matrix performs an application-directory swap followed by a real
  open of schema 8, schema 9 and current-schema ledgers. It verifies canonical data preservation,
  pre-migration backups, and coupled database/binary rollback on an injected migration failure.
  Published versions must be added to this fixture matrix before their Release is considered supported.
- Privacy gates enforce that the updater is the only outbound HTTP client, bundled web assets do not
  reference third-party resources, ledger API responses remain `no-store`, and the service worker
  never caches `/api/` data. The local server emits restrictive CSP, frame, MIME and referrer headers.
- Schema upgrades from every historical ledger schema (8 and 9) create and validate a checksummed
  backup before writes, run inside one transaction, preserve a migration audit record, and retain
  the original schema on failure. Desktop and CLI recovery paths require explicit confirmation.
- Provider imports converge on one raw-observation and canonical-transaction schema. Source IDs are
  open normalized strings (with compatibility for built-in enum values), and external adapters use a
  narrow persistence contract, so a new provider or statement version does not require a database
  or ledger-core change. Built-in parsing flows are registered outside the core importer.
- Native installer signature verification has a fail-closed cross-platform evidence contract:
  Windows runs Authenticode policy and timestamp verification, macOS requires both strict code-sign
  validation and Gatekeeper assessment, and Linux verifies a detached signature against a dedicated
  keyring. Every verifier pins the configured publisher/fingerprint and binds evidence to the exact
  installer digest; the publication gate rejects legacy self-reported evidence.
- Windows development builds produce a per-user MSI with a stable major-upgrade identity. A clean
  Windows runner installs an older package, upgrades it in place, uninstalls the current package and
  proves that the separately stored per-user ledger sentinel survives both operations. The MSI stays
  a preview until its application binaries, updater and installer receive trusted Authenticode
  signatures and verification evidence.
- The signed Windows workflow consumes a protected PKCS#12 certificate, signs and RFC 3161
  timestamps the main executable, updater and MSI, immediately verifies each Authenticode chain,
  pins the expected publisher in hash-bound evidence, and runs the strict Windows publication gate.
  No test certificate or unsigned fallback is accepted when signed mode is requested.
- macOS development builds produce a compressed read-only drag-to-Applications DMG. A macOS runner
  mounts it, verifies the application and Applications link, performs a disposable replacement
  upgrade/removal, and proves the separately stored Application Support ledger survives. Developer
  ID signing and notarization remain mandatory before enabling the macOS publication gate.
- The signed macOS workflow imports a protected Developer ID certificate into an ephemeral keychain,
  signs the hardened-runtime application and DMG with secure timestamps, requires an accepted Apple
  notarization result, staples and validates the ticket, runs Gatekeeper assessment, records native
  evidence and enters the strict macOS publication gate without an unsigned fallback.

Publisher credential validation and installer upgrades from every published version remain future
release batches. Linux AppImage construction, replacement-upgrade data preservation, detached GPG
signing and the strict native gate are implemented; the real publisher-key run remains pending.
