# FinancialBeancount Roadmap

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
