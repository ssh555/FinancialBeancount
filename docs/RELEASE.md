# Release Gate and External Credentials

The repository does not currently publish GitHub Releases. The desktop workflow produces reviewable
artifacts only; a successful workflow run is not permission to publish them.

## Implemented gates

- deterministic platform archives and SHA-256 manifests;
- Ed25519-signed update manifests with the public identity embedded in official builds;
- safe download, extraction, in-place replacement, health check and rollback;
- recoverable database migrations and a Windows/macOS/Linux upgrade matrix;
- privacy and offline-boundary tests.

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
