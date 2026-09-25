# Privacy and Network Boundary

[English](PRIVACY.md) | [简体中文](PRIVACY.zh-CN.md)

FinancialBeancount is a local-first ledger. Statement files, normalized transactions, original rows,
review history, statistics, backups and exports stay on the user's device unless the user explicitly
copies or shares an exported file.

## Network behavior

- The desktop ledger server binds to `127.0.0.1` on a random port. A non-loopback bind is rejected
  unless the operator explicitly configures an API token.
- The application has no telemetry, analytics, crash-reporting or advertising client.
- The only outbound client in the application package is the updater. It runs only after the user
  presses **Check for updates**, and sends the application version and ordinary HTTP request metadata
  to the configured HTTPS Release endpoint. It never reads or transmits the ledger database,
  statement files, transaction fields, account identifiers or backups.
- Disabling `FINANCIAL_BEANCOUNT_UPDATE_API` keeps the application completely offline. A custom
  endpoint must use HTTPS.

## Browser and cache behavior

- API responses use `Cache-Control: no-store` and are excluded by the service worker.
- The service worker caches only bundled static shell assets from the same origin.
- Content Security Policy permits scripts, styles and API connections only from the serving origin;
  frames and plug-in objects are disabled, and referrer information is suppressed.
- The browser stores only the local review actor label in persistent storage. API address and optional
  token use session storage and disappear when that browser session ends. Transaction data is not
  written to browser storage.

## Local diagnostics

Desktop startup and update diagnostics remain beside the per-user data or update staging directory.
They are never uploaded automatically. Verbose legacy CLI output may include local filenames or brief
transaction descriptions, so users should review console output before sharing it in a bug report.

## Release privacy gate

Automated tests fail if a new outbound HTTP client appears outside the updater, if bundled web assets
reference an external resource, if API responses become cacheable, or if the service worker starts
caching `/api/` responses. Any deliberate change to these boundaries requires an explicit privacy
review and an update to this document.
