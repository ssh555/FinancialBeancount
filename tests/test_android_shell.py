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


def test_android_debug_workflow_is_manual_and_uploads_only_debug_apk() -> None:
    workflow = (ROOT / ".github/workflows/android-build.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert ":app:assembleDebug" in workflow
    assert "app-debug.apk" in workflow
    assert "assembleRelease" not in workflow
