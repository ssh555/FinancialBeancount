from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_android_shell_reuses_core_and_limits_network_to_updates() -> None:
    manifest = (ROOT / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    activity = (
        ROOT / "android/app/src/main/java/io/github/ssh555/financialbeancount/MainActivity.kt"
    ).read_text(encoding="utf-8")
    build = (ROOT / "android/app/build.gradle.kts").read_text(encoding="utf-8")

    assert "android.permission.INTERNET" in manifest
    assert "android.permission.REQUEST_INSTALL_PACKAGES" in manifest
    assert 'android:authorities="${applicationId}.updates"' in manifest
    assert 'android:usesCleartextTraffic="false"' in manifest
    assert "WebView" not in activity
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
    assert "bridge.callAttr(" in activity and '"restore_archive"' in activity
    assert "androidx.documentfile:documentfile" in build

    updater = (
        ROOT
        / "android/app/src/main/java/io/github/ssh555/financialbeancount/AndroidUpdateManager.kt"
    ).read_text(encoding="utf-8")
    assert "api.github.com/repos/ssh555/FinancialBeancount/releases/latest" in updater
    assert 'optBoolean("draft")' in updater and 'optBoolean("prerelease")' in updater
    assert "FinancialBeancount-android-$version.apk" in updater
    assert 'MessageDigest.getInstance("SHA-256")' in updater
    assert "MAX_APK_BYTES" in updater
    assert "FileProvider.getUriForFile" in updater
    assert "canRequestPackageInstalls" in updater
    assert "cleanupDownloadedPackages" in updater
    assert "directory.listFiles()?.forEach" in updater
    assert "AndroidUpdateManager(this).cleanupDownloadedPackages()" in activity


def test_android_overview_handles_empty_balance_date_and_fits_period_controls() -> None:
    overview = (
        ROOT / "android/app/src/main/java/io/github/ssh555/financialbeancount/NativeOverviewView.kt"
    ).read_text(encoding="utf-8")

    assert 'it.isBlank() || it == "null"' in overview
    assert '?: "暂无日期"' in overview
    assert "minWidth = 0" in overview
    assert "LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f)" in overview
    assert "NativeUi.rounded(context, NativeUi.green" in overview
    assert "NativeUi.styleTree(summary)" in overview
    assert "NativeUi.styleTree(timeline)" in overview


def test_android_native_ui_reuses_the_web_default_palette() -> None:
    native_ui = (
        ROOT / "android/app/src/main/java/io/github/ssh555/financialbeancount/NativeUi.kt"
    ).read_text(encoding="utf-8")
    web_ui = (ROOT / "beancount_dedup/webapp/styles.css").read_text(encoding="utf-8")

    for color in ("23, 34, 29", "243, 242, 236", "255, 254, 250", "35, 92, 70"):
        assert color in native_ui
    for color in ("#17221d", "#f3f2ec", "#fffefa", "#235c46"):
        assert color in web_ui


def test_android_launches_native_mobile_navigation() -> None:
    activity = (
        ROOT / "android/app/src/main/java/io/github/ssh555/financialbeancount/MainActivity.kt"
    ).read_text(encoding="utf-8")
    shell = (
        ROOT / "android/app/src/main/java/io/github/ssh555/financialbeancount/NativeAppView.kt"
    ).read_text(encoding="utf-8")
    assert "NativeAppView(this, nativeClient, this)" in activity
    assert "setContentView(application)" in activity
    for page in ("概览", "交易", "审核", "数据"):
        assert f'"{page}"' in shell
    assert "ScrollView" in shell
    assert "BottomNavigationView" in shell
    assert "LABEL_VISIBILITY_LABELED" in shell
    assert "ic_overview" in shell and "ic_transactions" in shell
    assert "pageFactories" in shell
    assert "getOrPut(label)" in shell

    build = (ROOT / "android/app/build.gradle.kts").read_text(encoding="utf-8")
    assert "com.google.android.material:material" in build
    assert "androidx.recyclerview:recyclerview" in build


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
    assert 'setStatisticsPeriod("all", false)' in script
    assert 'period === "week"' in script
    assert "useCustomStatisticsPeriod" in script
    assert "await nativeRequest(payload)" in script
    assert 'classList.add("native-app")' in script


def test_android_workflow_builds_debug_or_fail_closed_signed_apk() -> None:
    workflow = (ROOT / ".github/workflows/android-build.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "workflow_call:" in workflow
    assert "push:" not in workflow
    assert ":app:assembleDebug" in workflow
    assert "app-debug.apk" in workflow
    assert ":app:assembleRelease" in workflow
    assert "apksigner" in workflow
    assert "sha256sum" in workflow
    assert 'version="${REQUESTED_VERSION#v}"' in workflow
    assert "1000000" in workflow and "1000" in workflow
    for secret in (
        "FINANCIAL_BEANCOUNT_ANDROID_KEYSTORE",
        "FINANCIAL_BEANCOUNT_ANDROID_KEYSTORE_PASSWORD",
        "FINANCIAL_BEANCOUNT_ANDROID_KEY_ALIAS",
        "FINANCIAL_BEANCOUNT_ANDROID_KEY_PASSWORD",
    ):
        assert secret in workflow


def test_android_release_version_and_signing_are_build_parameters() -> None:
    build = (ROOT / "android/app/build.gradle.kts").read_text(encoding="utf-8")
    assert 'providers.gradleProperty("appVersionCode")' in build
    assert 'providers.gradleProperty("appVersionName")' in build
    assert 'tasks.register("verifyReleaseSigning")' in build
    assert 'it.name == "packageRelease"' in build
    assert "unsigned Android release builds are forbidden" in build


def test_android_compose_uses_bom_and_semantic_theme_tokens() -> None:
    build = (ROOT / "android/app/build.gradle.kts").read_text(encoding="utf-8")
    root_build = (ROOT / "android/build.gradle.kts").read_text(encoding="utf-8")
    theme = (
        ROOT / "android/app/src/main/java/io/github/ssh555/financialbeancount/ComposeTheme.kt"
    ).read_text(encoding="utf-8")
    assert 'id("org.jetbrains.kotlin.plugin.compose")' in root_build
    assert 'platform("androidx.compose:compose-bom:' in build
    assert 'implementation("androidx.compose.material3:material3")' in build
    assert "compose = true" in build
    for token in ("Ink", "Muted", "Paper", "Card", "Line", "Primary", "Danger"):
        assert f"val {token}" in theme


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
    assert 'private var range = "all"' in overview
    assert 'metricRow("收支差额", data.getString("net_cash_flow")' in overview
    assert "收支差额不是账户当前余额" in overview


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
    assert "MaterialCardView" in source
    assert "TextInputLayout" in source
    assert "请输入有效日期" in source
    assert "请输入非零金额" in source
    assert "MaterialAlertDialogBuilder" in source

    source_filter = (
        ROOT / "android/app/src/main/java/io/github/ssh555/financialbeancount/SourceFilterButton.kt"
    ).read_text(encoding="utf-8")
    assert "/api/v1/sources" in source_filter
    assert "setMultiChoiceItems" in source_filter
    assert '"source=${URLEncoder.encode(it, "UTF-8")}"' in source_filter


def test_native_android_review_covers_all_queues_and_decisions() -> None:
    source = (
        ROOT / "android/app/src/main/java/io/github/ssh555/financialbeancount/NativeReviewView.kt"
    ).read_text(encoding="utf-8")
    for queue in ("imports", "matches", "refunds", "classifications", "warnings"):
        assert f'"{queue}"' in source
    assert "/api/v1/import-reviews/" in source
    assert 'decide(endpoint, "confirm")' in source
    assert 'decide(endpoint, "reject")' in source
    assert 'setTitle("选择处理方式")' in source
    assert 'if (type == "imports") "modify" else "confirm"' in source
    assert 'put("changes", changes)' in source
    assert "/api/v1/review/refunds/warnings/batch" in source
    assert 'resolveWarnings("escalate")' in source
    assert 'resolveWarnings("restore")' in source
    assert "MaterialCardView" in source
    assert "reviewDetails" in source
    assert "ChipGroup" in source
    assert "item.toString(2)" not in source


def test_native_data_view_has_about_and_double_confirmed_clear() -> None:
    source = (
        ROOT / "android/app/src/main/java/io/github/ssh555/financialbeancount/NativeDataView.kt"
    ).read_text(encoding="utf-8")
    assert "https://github.com/ssh555/FinancialBeancount" in source
    assert "https://github.com/CacinieP/FinancialBeancount" in source
    assert "许可证：MIT" in source
    assert 'setTitle("再次确认")' in source
    assert '"DELETE", "/api/v1/data"' in source
    assert 'put("confirmation", "DELETE ALL DATA")' in source


def test_native_android_data_surface_keeps_platform_file_boundaries() -> None:
    source = (
        ROOT / "android/app/src/main/java/io/github/ssh555/financialbeancount/NativeDataView.kt"
    ).read_text(encoding="utf-8")
    for operation in (
        "pickOneStatement",
        "pickMultipleStatements",
        "pickStatementFolder",
        "restorePortableArchive",
        "exportTransactions",
        "exportPortableArchive",
    ):
        assert f"fun {operation}" in source
    assert "data class QueueItem" in source
    assert 'setTitle("覆盖当前账本？")' in source
    assert "/api/v1/import-formats" in source
    assert "/api/v1/imports" in source
    assert "fun acceptFiles(" in source
    assert "来源账户" in source
    assert "MaterialAutoCompleteTextView" in source
    assert "TextInputLayout" in source
    assert "MaterialCardView" in source
    activity = (
        ROOT / "android/app/src/main/java/io/github/ssh555/financialbeancount/MainActivity.kt"
    ).read_text(encoding="utf-8")
    assert "MainActivity : ComponentActivity(), NativeDataView.Host" in activity
    assert "nativeDataView?.acceptFiles(nativeFiles, nativeSkipped)" in activity
    assert "override fun exportTransactions(format: String)" in activity
    assert "override fun exportPortableArchive()" in activity
