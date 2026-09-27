# Android Delivery Architecture

[English](ANDROID.md) | [简体中文](ANDROID.zh-CN.md)

Android must continue to use the unified ledger schema, import adapters, review rules and portable
archive. It must not introduce a mobile-only database or duplicate business logic.

## Decided boundaries

- Embed the Python 3.10+ ledger engine in the APK/AAB with Chaquopy 17.x; minimum Android API 24.
- Kotlin calls `beancount_dedup.android_bridge.dispatch` with JSON directly; no localhost HTTP server.
- Keep SQLite only in app-private storage. Updates preserve it; uninstall follows Android's normal
  application-data lifecycle.
- Load bundled static assets through `WebViewAssetLoader` at
  `https://appassets.androidplatform.net`; disable file/content access, cleartext traffic and release
  debugging, and never load arbitrary remote pages.
- Use Android's Storage Access Framework for one file, multiple selected files and a selected
  directory. Kotlin reads only user-granted content and sends the existing import API its base64
  payload.
- Export through the system create-document UI. Do not request broad all-files access.
- Formal updates retain the application ID, increment versionCode, and use the same Android signing
  identity or a valid key-rotation proof, avoiding uninstall/reinstall.

## Current increment

This increment provides the minimal Kotlin/Gradle project, socket-free bridge, local-origin-only
WebView and asset allowlist, with tests for health, unified-schema initialization, mobile transaction
creation/listing and path rejection. The Android debug app now uses the system picker for one file,
multiple files or a folder and reuses the web batch-import queue; unsupported, oversized or unreadable
files are reported by name. A manual GitHub Actions job produces a debug APK only; it neither publishes
nor signs a formal build. The next increment is the system export bridge.

No publishable Android APK/AAB exists yet. These bridge tests must not be represented as a complete
Android application or release-ready artifact.
