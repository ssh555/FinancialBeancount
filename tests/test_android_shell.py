from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_android_shell_reuses_core_without_network_permission() -> None:
    manifest = (ROOT / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    activity = (
        ROOT / "android/app/src/main/java/io/github/ssh555/financialbeancount/MainActivity.kt"
    ).read_text(encoding="utf-8")
    build = (ROOT / "android/app/build.gradle.kts").read_text(encoding="utf-8")

    assert "android.permission.INTERNET" not in manifest
    assert 'android:usesCleartextTraffic="false"' in manifest
    assert "allowFileAccess = false" in activity
    assert "allowContentAccess = false" in activity
    assert "MIXED_CONTENT_NEVER_ALLOW" in activity
    assert "appassets.androidplatform.net" in activity
    assert 'srcDir(layout.buildDirectory.dir("generated/python"))' in build
    assert 'from(rootProject.projectDir.parentFile.resolve("beancount_dedup"))' in build
    assert 'endsWith("PythonSources")' in build
    assert "sourceCompatibility = JavaVersion.VERSION_17" in build
    assert "ActivityResultContracts.OpenDocument()" in activity
    assert "ActivityResultContracts.OpenMultipleDocuments()" in activity
    assert "ActivityResultContracts.OpenDocumentTree()" in activity
    assert "DocumentFile.fromTreeUri" in activity
    assert "Intent.ACTION_CREATE_DOCUMENT" in activity
    assert "contentResolver.openOutputStream" in activity
    assert "fun saveDocument(" in activity
    assert "fun pickPortableArchive()" in activity
    assert "bridge.callAttr(" in activity and '"restore_archive"' in activity
    assert "webView.webChromeClient = LocalChromeClient()" in activity
    assert "override fun onJsConfirm(" in activity
    assert 'setPositiveButton("继续")' in activity
    assert "fun requestAsync(" in activity
    assert "Executors.newFixedThreadPool(3)" in activity
    assert "androidx.documentfile:documentfile" in build


def test_web_client_uses_native_bridge_before_http_fetch() -> None:
    script = (ROOT / "beancount_dedup/webapp/app.js").read_text(encoding="utf-8")
    native = script.index("FinancialBeancountNative?.request")
    network = script.index("await fetch")
    assert native < network
    assert 'method: options.method || "GET"' in script
    assert "JSON.parse(options.body)" in script
    assert "acceptNativeImportFiles" in script
    assert "file.nativeBase64" in script
    assert 'single: "pickSingleFile"' in script
    assert "saveWithNativePicker" in script
    assert "reportNativeExportResult" in script
    assert "textAsBase64" in script
    assert "reportNativeArchiveImportResult" in script
    assert "恢复完整归档会覆盖此设备当前账本" in script
    assert 'setStatisticsPeriod("month", false)' in script
    assert 'period === "week"' in script
    assert "useCustomStatisticsPeriod" in script
    assert "await nativeRequest(payload)" in script
    assert 'classList.add("native-app")' in script


def test_android_debug_workflow_is_manual_and_uploads_only_debug_apk() -> None:
    workflow = (ROOT / ".github/workflows/android-build.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert ":app:assembleDebug" in workflow
    assert "app-debug.apk" in workflow
    assert "assembleRelease" not in workflow


def test_native_android_overview_uses_async_core_client() -> None:
    client = (
        ROOT / "android/app/src/main/java/io/github/ssh555/financialbeancount/NativeLedgerClient.kt"
    ).read_text(encoding="utf-8")
    overview = (
        ROOT / "android/app/src/main/java/io/github/ssh555/financialbeancount/NativeOverviewView.kt"
    ).read_text(encoding="utf-8")
    assert "Executors.newFixedThreadPool(3)" in client
    assert 'getModule("beancount_dedup.android_bridge")' in client
    assert "/api/v1/statistics/summary" in overview
    assert "/api/v1/statistics/timeline" in overview
    assert '"日" to "day"' in overview
    assert "minHeight = dp(48)" in overview


def test_native_android_transactions_are_paginated_and_searchable() -> None:
    source = (
        ROOT
        / "android/app/src/main/java/io/github/ssh555/financialbeancount/NativeTransactionsView.kt"
    ).read_text(encoding="utf-8")
    assert "page_size=30" in source
    assert "URLEncoder.encode" in source
    assert 'more.text = "加载更多"' in source
    assert '"GET", "/api/v1/transactions/$id"' in source
    assert 'text = "记一笔"' in source
    assert 'mutate("PATCH"' in source
    assert 'mutate("DELETE"' in source
    assert "/api/v1/deleted-transactions" in source
    assert '}/restore"' in source


def test_native_android_review_covers_all_queues_and_decisions() -> None:
    source = (
        ROOT / "android/app/src/main/java/io/github/ssh555/financialbeancount/NativeReviewView.kt"
    ).read_text(encoding="utf-8")
    for queue in ("imports", "matches", "refunds", "classifications"):
        assert f'"{queue}"' in source
    assert "/api/v1/import-reviews/" in source
    assert 'decide(endpoint, "confirm")' in source
    assert 'decide(endpoint, "reject")' in source
    assert 'builder.setPositiveButton("人工修改")' in source
    assert 'if (type == "imports") "modify" else "confirm"' in source
    assert 'put("changes", changes)' in source
