package io.github.ssh555.financialbeancount

import android.annotation.SuppressLint
import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.util.Base64
import android.webkit.JavascriptInterface
import android.webkit.JsResult
import android.webkit.WebChromeClient
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
import java.util.concurrent.Executors
import kotlin.concurrent.thread

private const val APP_ORIGIN = "https://appassets.androidplatform.net"
private const val MAX_IMPORT_BYTES = 50L * 1024 * 1024
private const val MAX_ARCHIVE_BYTES = 200L * 1024 * 1024
private val IMPORT_SUFFIXES = setOf("csv", "xlsx", "pdf")

private data class SelectedDocument(val document: DocumentFile, val relativePath: String)
private data class PendingExport(val filename: String, val mimeType: String, val contentBase64: String)

class MainActivity : ComponentActivity(), NativeDataView.Host {
    private lateinit var bridge: PyObject
    private lateinit var webView: WebView
    private var nativeDataView: NativeDataView? = null
    private val requestExecutor = Executors.newFixedThreadPool(3)
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
    private val archivePicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) restorePortableArchive(uri)
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

    override fun pickOneStatement() = singleFilePicker.launch(arrayOf("*/*"))
    override fun pickMultipleStatements() = multipleFilePicker.launch(arrayOf("*/*"))
    override fun pickStatementFolder() = folderPicker.launch(null)
    override fun restorePortableArchive() = archivePicker.launch(arrayOf("application/zip", "application/octet-stream"))

    override fun exportTransactions(format: String) {
        thread(name = "native-transaction-export") {
            try {
                val database = getDatabasePath("ledger.sqlite3").absolutePath
                val request = JSONObject().put("method", "GET").put("target", "/api/v1/exports/transactions?format=$format")
                val response = JSONObject(bridge.callAttr("dispatch", database, request.toString()).toString())
                val data = response.getJSONObject("body").getJSONArray("data")
                val content = if (format == "csv") transactionCsv(data) else response.getJSONObject("body").toString(2)
                beginExport(
                    PendingExport(
                        "financial-beancount-${java.time.LocalDate.now()}.$format",
                        if (format == "csv") "text/csv" else "application/json",
                        Base64.encodeToString(content.toByteArray(Charsets.UTF_8), Base64.NO_WRAP),
                    ),
                )
            } catch (error: Exception) {
                nativeDataView?.post { nativeDataView?.showProgress(error.message ?: "交易导出失败") }
            }
        }
    }

    override fun exportPortableArchive() {
        thread(name = "native-archive-export") {
            try {
                val database = getDatabasePath("ledger.sqlite3").absolutePath
                val request = JSONObject().put("method", "GET").put("target", "/api/v1/exports/portable-archive")
                val data = JSONObject(bridge.callAttr("dispatch", database, request.toString()).toString())
                    .getJSONObject("body").getJSONObject("data")
                beginExport(PendingExport(data.getString("filename"), "application/zip", data.getString("content_base64")))
            } catch (error: Exception) {
                nativeDataView?.post { nativeDataView?.showProgress(error.message ?: "完整归档导出失败") }
            }
        }
    }

    private fun beginExport(export: PendingExport) {
        if (pendingExport != null) error("已有文件正在等待保存")
        pendingExport = export
        runOnUiThread {
            exportPicker.launch(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = export.mimeType
                putExtra(Intent.EXTRA_TITLE, export.filename)
            })
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
        webView.webChromeClient = LocalChromeClient()
        webView.webViewClient = LocalOnlyClient()
        webView.loadUrl("$APP_ORIGIN/index.html")
    }

    override fun onDestroy() {
        requestExecutor.shutdownNow()
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
        fun requestAsync(requestId: String, requestJson: String) {
            requestExecutor.execute {
                val response = try {
                    request(requestJson)
                } catch (error: Exception) {
                    JSONObject()
                        .put("status", 500)
                        .put(
                            "body",
                            JSONObject().put(
                                "error",
                                JSONObject().put("message", error.message ?: "本地账本请求失败"),
                            ),
                        )
                        .toString()
                }
                webView.post {
                    webView.evaluateJavascript(
                        "globalThis.resolveNativeRequest(${JSONObject.quote(requestId)}, ${JSONObject.quote(response)})",
                        null,
                    )
                }
            }
        }

        @JavascriptInterface
        fun pickSingleFile() = runOnUiThread { singleFilePicker.launch(arrayOf("*/*")) }

        @JavascriptInterface
        fun pickMultipleFiles() = runOnUiThread { multipleFilePicker.launch(arrayOf("*/*")) }

        @JavascriptInterface
        fun pickFolder() = runOnUiThread { folderPicker.launch(null) }

        @JavascriptInterface
        fun pickPortableArchive() = runOnUiThread {
            archivePicker.launch(arrayOf("application/zip", "application/octet-stream"))
        }

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

    private fun restorePortableArchive(uri: Uri) {
        thread(name = "ledger-archive-restorer") {
            try {
                val bytes = contentResolver.openInputStream(uri)?.use { it.readBytes() }
                    ?: error("无法打开完整归档")
                if (bytes.size > MAX_ARCHIVE_BYTES) error("完整归档超过 200 MiB")
                val database = getDatabasePath("ledger.sqlite3").absolutePath
                bridge.callAttr(
                    "restore_archive",
                    database,
                    Base64.encodeToString(bytes, Base64.NO_WRAP),
                )
                reportArchiveImportResult(true, "完整账本已恢复")
            } catch (error: Exception) {
                reportArchiveImportResult(false, error.message ?: "完整归档恢复失败")
            }
        }
    }

    private fun reportArchiveImportResult(success: Boolean, message: String) {
        nativeDataView?.post { nativeDataView?.showProgress(message) }
        if (nativeDataView != null) return
        webView.post {
            webView.evaluateJavascript(
                "globalThis.reportNativeArchiveImportResult($success, ${JSONObject.quote(message)})",
                null,
            )
        }
    }

    private fun reportExportResult(success: Boolean, message: String) {
        nativeDataView?.post { nativeDataView?.showProgress(message) }
        if (nativeDataView != null) return
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
        val nativeFiles = mutableListOf<NativeDataView.SelectedFile>()
        val nativeSkipped = mutableListOf<NativeDataView.QueueItem>()
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
                nativeSkipped += NativeDataView.QueueItem(selected.relativePath, "未处理", reason)
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
                nativeFiles += NativeDataView.SelectedFile(
                    name,
                    selected.relativePath,
                    Base64.encodeToString(bytes, Base64.NO_WRAP),
                )
            } catch (error: Exception) {
                skipped.put(
                    JSONObject()
                        .put("name", selected.relativePath)
                        .put("reason", error.message ?: "无法读取文件"),
                )
                nativeSkipped += NativeDataView.QueueItem(
                    selected.relativePath,
                    "未处理",
                    error.message ?: "无法读取文件",
                )
            }
        }
        nativeDataView?.post {
            nativeDataView?.acceptFiles(nativeFiles, nativeSkipped)
        }
        if (nativeDataView != null) return
        val payload = JSONObject().put("files", files).put("skipped", skipped).toString()
        webView.post {
            webView.evaluateJavascript(
                "globalThis.acceptNativeImportFiles(${JSONObject.quote(payload)})",
                null,
            )
        }
    }

    private fun transactionCsv(rows: JSONArray): String {
        val columns = listOf(
            "canonical_id", "booking_date", "transaction_time", "amount", "direction",
            "merchant", "category", "payment_channel", "funding_account", "tx_type",
            "status", "review_status", "notes", "source_count",
        )
        fun quote(value: String) = "\"${value.replace("\"", "\"\"")}\""
        return buildString {
            append('\uFEFF').append(columns.joinToString(",")).append("\r\n")
            for (index in 0 until rows.length()) {
                val row = rows.getJSONObject(index)
                append(columns.joinToString(",") { quote(row.optString(it)) }).append("\r\n")
            }
        }
    }

    private inner class LocalChromeClient : WebChromeClient() {
        override fun onJsConfirm(
            view: WebView,
            url: String,
            message: String,
            result: JsResult,
        ): Boolean {
            AlertDialog.Builder(this@MainActivity)
                .setMessage(message)
                .setPositiveButton("继续") { _, _ -> result.confirm() }
                .setNegativeButton("取消") { _, _ -> result.cancel() }
                .setOnCancelListener { result.cancel() }
                .show()
            return true
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
