package io.github.ssh555.financialbeancount

import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.Base64
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.documentfile.provider.DocumentFile
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File
import kotlin.concurrent.thread

private const val MAX_IMPORT_BYTES = 50L * 1024 * 1024
private const val MAX_ARCHIVE_BYTES = 200L * 1024 * 1024
private val IMPORT_SUFFIXES = setOf("csv", "xlsx", "pdf")

private data class SelectedDocument(val document: DocumentFile, val relativePath: String)
private data class PendingExport(val filename: String, val mimeType: String, val contentBase64: String)

class MainActivity : ComponentActivity(), NativeDataView.Host {
    private lateinit var bridge: PyObject
    private lateinit var nativeClient: NativeLedgerClient
    private var nativeDataView: NativeDataView? = null
    @Volatile private var pendingExport: PendingExport? = null
    @Volatile private var pendingUpdateApk: File? = null

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

    override fun checkForUpdates() {
        nativeDataView?.showProgress("正在检查 GitHub Release…")
        thread(name = "android-update-check") {
            try {
                val manager = AndroidUpdateManager(this)
                val update = manager.check()
                runOnUiThread {
                    if (update == null) nativeDataView?.showProgress("当前已是最新版本（${BuildConfig.VERSION_NAME}）")
                    else AlertDialog.Builder(this)
                        .setTitle("发现新版本 ${update.version}")
                        .setMessage("下载大小：${update.apkSize / 1024 / 1024.0} MiB\n\n${update.notes.take(1200)}")
                        .setPositiveButton("下载并更新") { _, _ -> downloadAndInstall(update) }
                        .setNegativeButton("稍后", null)
                        .show()
                }
            } catch (error: Exception) {
                nativeDataView?.post { nativeDataView?.showProgress(error.message ?: "检查更新失败") }
            }
        }
    }

    private fun downloadAndInstall(update: AndroidUpdateInfo) {
        nativeDataView?.showProgress("正在下载并校验 ${update.apkName}…")
        thread(name = "android-update-download") {
            try {
                val manager = AndroidUpdateManager(this)
                val apk = manager.download(update)
                runOnUiThread {
                    if (manager.install(apk)) nativeDataView?.showProgress("校验通过，已交给系统安装器")
                    else {
                        pendingUpdateApk = apk
                        nativeDataView?.showProgress("请允许此来源安装应用，返回后将继续安装")
                    }
                }
            } catch (error: Exception) {
                nativeDataView?.post { nativeDataView?.showProgress(error.message ?: "更新下载失败") }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        val apk = pendingUpdateApk ?: return
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O || packageManager.canRequestPackageInstalls()) {
            pendingUpdateApk = null
            if (AndroidUpdateManager(this).install(apk)) nativeDataView?.showProgress("权限已允许，已交给系统安装器")
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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        bridge = Python.getInstance().getModule("beancount_dedup.android_bridge")
        nativeClient = NativeLedgerClient(this)
        val application = NativeAppView(this, nativeClient, this)
        nativeDataView = application.dataView
        setContentView(application)
    }

    override fun onDestroy() {
        nativeClient.close()
        super.onDestroy()
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

    private fun reportArchiveImportResult(@Suppress("UNUSED_PARAMETER") success: Boolean, message: String) {
        nativeDataView?.post { nativeDataView?.showProgress(message) }
    }

    private fun reportExportResult(@Suppress("UNUSED_PARAMETER") success: Boolean, message: String) {
        nativeDataView?.post { nativeDataView?.showProgress(message) }
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
                nativeSkipped += NativeDataView.QueueItem(selected.relativePath, "未处理", reason)
                return@forEach
            }
            try {
                val bytes = contentResolver.openInputStream(document.uri)?.use { it.readBytes() }
                    ?: error("无法打开文件")
                if (bytes.size > MAX_IMPORT_BYTES) error("文件超过 50 MiB")
                nativeFiles += NativeDataView.SelectedFile(
                    name,
                    selected.relativePath,
                    Base64.encodeToString(bytes, Base64.NO_WRAP),
                )
            } catch (error: Exception) {
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
    }

    private fun transactionCsv(rows: org.json.JSONArray): String {
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

}
