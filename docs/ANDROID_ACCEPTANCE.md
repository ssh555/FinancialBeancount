# Android Device Acceptance

[English](ANDROID_ACCEPTANCE.md) | [简体中文](ANDROID_ACCEPTANCE.zh-CN.md)

This checklist validates the current debug APK. It does not certify release signing, store
distribution or the upgrade chain. Android 7.0 (API 24) is the minimum supported version.

## Obtain and install the debug APK

1. Open **Android debug build** in GitHub Actions, manually run it for `main`, and wait for success.
2. Download the `FinancialBeancount-android-debug` artifact from the run, then extract
   `app-debug.apk`.
3. Transfer the APK to the test device and allow installation from that source, or use ADB:

```bash
adb install app-debug.apk
```

GitHub Actions debug packages are only for current functional acceptance. Debug signing identities
may differ between runs, so they must not be used to validate in-place upgrades. A formal Release
must retain the publisher's signing identity, increment `versionCode`, and pass ledger-preserving
upgrade tests.

## Prepare one complete-ledger file

Run the following on the desktop against the prepared complete statement directory:

```bash
python scripts/acceptance_full_ledger.py \
  --bills /path/to/private/statements \
  --output /path/to/new-empty-output-directory
```

Use the generated `complete-ledger.financial-beancount.zip` only when the report contains no
unprocessed files. Statements, databases, reports and archives are private data and must never be
uploaded to GitHub or stored as Actions artifacts.

Before device acceptance, also run the statistics-conservation validator against the generated
database:

```bash
python scripts/validate_complete_ledger.py \
  --database /path/to/complete-ledger.sqlite3 \
  --output /path/to/complete-ledger-validation.json
```

In the validation report, `summary.net_cash_flow` is cumulative cash flow for the ledger period,
not a current balance. Use `account_balance.known_balance` for the known balance backed by the
latest raw bank cash balances plus clearly identifiable internal bank products (currently CMB
Zhaochaobao and ICBC Tiantianying). External fund platforms such as Tiantian Fund and payment
accounts without statement balances are excluded. During acceptance, also inspect
`cash_accounts`, `internal_products`, and their as-of dates.

Generate the read-only data-quality audit as well. It flags suspected duplicates, merge candidates,
and investment/fund flows without modifying the ledger:

```bash
python scripts/audit_complete_ledger.py \
  --database /path/to/complete-ledger.sqlite3 \
  --output /path/to/complete-ledger-data-quality.json
```

A `high` priority still means review first, not automatic deletion. Equal amounts and balances can
also be legitimate consecutive entries caused by an internal-product automatic redemption.

Then run the primary mobile read-path baseline. Do not proceed to device acceptance if any item
exceeds its reported limit:

```bash
python scripts/benchmark_mobile.py \
  --database /path/to/complete-ledger.sqlite3 \
  --output /path/to/mobile-performance.json
```

## Device round trip

1. After first launch, disconnect networking and confirm Overview, Transactions, Review and Settings
   still open.
2. Open **Settings → Data and migration → Restore complete archive**, acknowledge the replacement
   warning, and select only the ZIP above.
3. Confirm the restore succeeds. Spot-check dates, amounts, merchants, categories, source counts and
   review queues, including searches for at least three known transactions. Confirm that the
   Overview account balance agrees with the desktop validation report and is not confused with
   cumulative net cash flow.
4. Create one test transaction, edit it, soft-delete it, and restore it from Trash.
5. Export CSV, JSON and a complete archive. Confirm the system save UI accepts a chosen destination
   and each resulting file can be opened again.
6. Transfer the mobile archive back to the desktop, validate it, and restore it to a new path which
   does not already exist:

```bash
python -m beancount_dedup.archive_cli inspect --archive /path/to/mobile-export.zip
python -m beancount_dedup.archive_cli import \
  --archive /path/to/mobile-export.zip \
  --database /path/to/new-mobile-restored.sqlite3
```

7. Optionally use a small statement subset to test the one-file, multiple-file and folder pickers.
   Unsupported extensions, oversized files, unsupported content and damaged statements must be
   reported by filename as not queued or unprocessed, without partial ledger writes.

## Overview and transaction filtering

- Summary metrics and every timeline card on Overview open the matching transaction result set.
  The destination preserves the applicable date range, sources and other filters, and Back returns
  to the previous Overview position.
- Overview supports multi-select filtering by platform, bank and individual account so users can
  inspect one source or a combination of sources. Account balance remains explicitly independent
  of source filters.
- “All sources” uses explicit select-all semantics: every source is selected by default, deselecting
  one excludes it, and selecting none yields an empty result rather than being interpreted as all.
- Transactions treats source as the top-level scope and also supports combined filters for date or
  custom period, income/expense direction, amount range, category, merchant or notes, and pending
  review status.
- Active filters stay visible and support individual removal and clear-all. An empty filtered result
  must be distinguished from an empty ledger.
- Filtering, pagination, opening details and navigating back preserve list position and active
  conditions.

## Review priority and actions

Process **Required** items first, then inspect non-blocking Warnings. The complete outcome set for a
Required item is: accept into the ledger, correct and accept, link/merge, keep independent, exclude,
or defer. Exclusion affects statistics and exports but preserves imported source evidence; deferred
items remain in the Required queue.

A Warning is an ambiguous or partial-refund decision that the system has already applied. It supports
multi-select and select-all batch handling:

- **Batch accept** needs no second confirmation. It keeps the automatic relationship, clears the
  Warning, and records it under **Accepted**, where it can be restored to Warning at any time.
- **Reject** undoes the automatic relationship and moves it to Required without deleting source data;
  finish it there using the complete outcome set above.

During acceptance, exercise batch accept, restore from Accepted, and rejection rollback, and confirm
that all three operations leave audit events.

## Pass criteria

- Ledger, import, statistics and export remain usable offline and need no broad all-files permission;
  network and package-install permissions are used only for a user-triggered update.
- **Check for updates** ignores drafts and prereleases, accepts only a versioned APK with its SHA-256
  file, and never launches the installer after verification failure.
- One complete archive restores successfully; a damaged archive fails without harming the current
  ledger.
- Core counts in the desktop acceptance report agree with device spot checks, and the added test
  transaction plus its audit operations survive the exported mobile archive round trip.
- CSV, JSON and the complete archive save to user-selected locations.
- There are no crashes, blank pages, silently skipped files, or formal upgrade design which requires
  uninstall/reinstall.

Record only the device model, Android version, APK commit, acceptance time, passed items and failures;
this small project does not need a separate test-management system.
