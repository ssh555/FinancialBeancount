package io.github.ssh555.financialbeancount

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.util.Base64
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.documentfile.provider.DocumentFile
import androidx.webkit.WebViewClientCompat
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.ByteArrayInputStream
import org.json.JSONArray
import org.json.JSONObject
import kotlin.concurrent.thread

private const val APP_ORIGIN = "https://appassets.androidplatform.net"
private const val MAX_IMPORT_BYTES = 50L * 1024 * 1024
private val IMPORT_SUFFIXES = setOf("csv", "xlsx", "pdf")

private data class SelectedDocument(val document: DocumentFile, val relativePath: String)
private data class PendingExport(val filename: String, val mimeType: String, val contentBase64: String)

class MainActivity : ComponentActivity() {
    private lateinit var bridge: PyObject
    private lateinit var webView: WebView
    @Volatile private var pendingExport: PendingExport? = null

    private val singleFilePicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        importSelectedUris(listOfNotNull(uri))
    }
    private val multipleFilePicker = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        importSelectedUris(uris)
    }
    private val folderPicker = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) importSelectedFolder(uri)
    }
    private val exportPicker = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val export = pendingExport
        val uri = result.data?.data
        if (result.resultCode != RESULT_OK || uri == null || export == null) {
            pendingExport = null
            reportExportResult(false, "已取消保存")
        } else {
            writeExport(uri, export)
        }
    }

    @SuppressLint("SetJavaScriptEnabled", "AddJavascriptInterface")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        bridge = Python.getInstance().getModule("beancount_dedup.android_bridge")

        webView = WebView(this)
        setContentView(webView)
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
        }
        webView.addJavascriptInterface(LedgerJavascriptBridge(), "FinancialBeancountNative")
        webView.webViewClient = LocalOnlyClient()
        webView.loadUrl("$APP_ORIGIN/index.html")
    }

    override fun onDestroy() {
        webView.removeJavascriptInterface("FinancialBeancountNative")
        webView.destroy()
        super.onDestroy()
    }

    private inner class LedgerJavascriptBridge {
        @JavascriptInterface
        fun request(requestJson: String): String {
            val database = getDatabasePath("ledger.sqlite3").absolutePath
            return bridge.callAttr("dispatch", database, requestJson).toString()
        }

        @JavascriptInterface
        fun pickSingleFile() = runOnUiThread { singleFilePicker.launch(arrayOf("*/*")) }

        @JavascriptInterface
        fun pickMultipleFiles() = runOnUiThread { multipleFilePicker.launch(arrayOf("*/*")) }

        @JavascriptInterface
        fun pickFolder() = runOnUiThread { folderPicker.launch(null) }

        @JavascriptInterface
        @Synchronized
        fun saveDocument(filename: String, mimeType: String, contentBase64: String): Boolean {
            if (pendingExport != null) return false
            pendingExport = PendingExport(filename, mimeType, contentBase64)
            runOnUiThread {
                try {
                    exportPicker.launch(
                        Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                            addCategory(Intent.CATEGORY_OPENABLE)
                            type = mimeType
                            putExtra(Intent.EXTRA_TITLE, filename)
                        },
                    )
                } catch (error: Exception) {
                    pendingExport = null
                    reportExportResult(false, error.message ?: "无法打开保存界面")
                }
            }
            return true
        }
    }

    private fun writeExport(uri: Uri, export: PendingExport) {
        thread(name = "ledger-export-writer") {
            try {
                val bytes = Base64.decode(export.contentBase64, Base64.DEFAULT)
                contentResolver.openOutputStream(uri, "w")?.use { it.write(bytes) }
                    ?: error("无法写入目标文件")
                reportExportResult(true, "已保存 ${export.filename}")
            } catch (error: Exception) {
                reportExportResult(false, error.message ?: "保存失败")
            } finally {
                pendingExport = null
            }
        }
    }

    private fun reportExportResult(success: Boolean, message: String) {
        webView.post {
            webView.evaluateJavascript(
                "globalThis.reportNativeExportResult($success, ${JSONObject.quote(message)})",
                null,
            )
        }
    }

    private fun importSelectedUris(uris: List<Uri>) {
        thread(name = "statement-file-reader") {
            val documents = uris.mapNotNull { uri ->
                DocumentFile.fromSingleUri(this, uri)?.let { SelectedDocument(it, it.name ?: "未命名文件") }
            }
            deliverSelectedDocuments(documents)
        }
    }

    private fun importSelectedFolder(uri: Uri) {
        thread(name = "statement-folder-reader") {
            val root = DocumentFile.fromTreeUri(this, uri)
            val documents = if (root == null) emptyList() else collectFiles(root, "")
            deliverSelectedDocuments(documents)
        }
    }

    private fun collectFiles(directory: DocumentFile, prefix: String): List<SelectedDocument> =
        directory.listFiles().flatMap { child ->
            val name = child.name ?: "未命名文件"
            val path = if (prefix.isEmpty()) name else "$prefix/$name"
            when {
                child.isDirectory -> collectFiles(child, path)
                child.isFile -> listOf(SelectedDocument(child, path))
                else -> emptyList()
            }
        }

    private fun deliverSelectedDocuments(documents: List<SelectedDocument>) {
        val files = JSONArray()
        val skipped = JSONArray()
        documents.forEach { selected ->
            val document = selected.document
            val name = document.name ?: selected.relativePath
            val suffix = name.substringAfterLast('.', "").lowercase()
            val size = document.length()
            val reason = when {
                suffix !in IMPORT_SUFFIXES -> "不支持的文件类型"
                size > MAX_IMPORT_BYTES -> "文件超过 50 MiB"
                else -> null
            }
            if (reason != null) {
                skipped.put(JSONObject().put("name", selected.relativePath).put("reason", reason))
                return@forEach
            }
            try {
                val bytes = contentResolver.openInputStream(document.uri)?.use { it.readBytes() }
                    ?: error("无法打开文件")
                if (bytes.size > MAX_IMPORT_BYTES) error("文件超过 50 MiB")
                files.put(
                    JSONObject()
                        .put("name", name)
                        .put("relativePath", selected.relativePath)
                        .put("size", bytes.size)
                        .put("lastModified", document.lastModified())
                        .put("contentBase64", Base64.encodeToString(bytes, Base64.NO_WRAP)),
                )
            } catch (error: Exception) {
                skipped.put(
                    JSONObject()
                        .put("name", selected.relativePath)
                        .put("reason", error.message ?: "无法读取文件"),
                )
            }
        }
        val payload = JSONObject().put("files", files).put("skipped", skipped).toString()
        webView.post {
            webView.evaluateJavascript(
                "globalThis.acceptNativeImportFiles(${JSONObject.quote(payload)})",
                null,
            )
        }
    }

    private inner class LocalOnlyClient : WebViewClientCompat() {
        override fun shouldInterceptRequest(
            view: WebView,
            request: WebResourceRequest,
        ): WebResourceResponse? {
            if (request.url.scheme != "https" || request.url.host != "appassets.androidplatform.net") {
                return blockedResponse()
            }
            val path = request.url.path ?: "/"
            return try {
                val bytes = bridge.callAttr("web_asset", path).toJava(ByteArray::class.java)
                val contentType = bridge.callAttr("web_asset_content_type", path).toString()
                val parts = contentType.split(";", limit = 2)
                WebResourceResponse(
                    parts[0],
                    if (parts.size == 2) "UTF-8" else null,
                    ByteArrayInputStream(bytes),
                )
            } catch (_: Exception) {
                blockedResponse()
            }
        }

        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
            request.url.scheme != "https" || request.url.host != "appassets.androidplatform.net"

        private fun blockedResponse() = WebResourceResponse(
            "text/plain",
            "UTF-8",
            404,
            "Not Found",
            mapOf("Cache-Control" to "no-store"),
            ByteArrayInputStream(ByteArray(0)),
        )
    }
}
