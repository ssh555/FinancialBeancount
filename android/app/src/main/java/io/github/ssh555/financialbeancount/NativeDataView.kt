package io.github.ssh555.financialbeancount

import android.app.AlertDialog
import android.content.Context
import android.graphics.Typeface
import android.view.Gravity
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Spinner
import android.widget.ArrayAdapter
import android.widget.TextView
import org.json.JSONObject

class NativeDataView(context: Context, private val client: NativeLedgerClient, private val host: Host) : LinearLayout(context) {
    interface Host {
        fun pickOneStatement()
        fun pickMultipleStatements()
        fun pickStatementFolder()
        fun restorePortableArchive()
        fun exportTransactions(format: String)
        fun exportPortableArchive()
    }

    private val queue = LinearLayout(context)
    private val progress = TextView(context)
    private val importButton = Button(context)
    private val items = mutableListOf<QueueItem>()
    private var formats = emptyList<ImportFormat>()

    init {
        orientation = VERTICAL
        setPadding(dp(16), dp(16), dp(16), dp(24))
        addView(TextView(context).apply { text = "数据与迁移"; textSize = 26f; setTypeface(typeface, Typeface.BOLD) })
        addView(section("导入官方账单"))
        addView(action("选择一个文件") { host.pickOneStatement() })
        addView(action("选择多个文件") { host.pickMultipleStatements() })
        addView(action("选择文件夹") { host.pickStatementFolder() })
        queue.orientation = VERTICAL
        addView(queue)
        importButton.text = "导入队列"
        importButton.minHeight = dp(48)
        importButton.isEnabled = false
        importButton.setOnClickListener { importNext(0, 0, 0) }
        addView(importButton)
        progress.gravity = Gravity.CENTER
        progress.setPadding(0, dp(10), 0, dp(10))
        addView(progress)
        addView(section("完整账本"))
        addView(action("恢复完整归档") {
            AlertDialog.Builder(context)
                .setTitle("覆盖当前账本？")
                .setMessage("请先导出备份。恢复成功后，当前设备账本会被完整归档替换。")
                .setPositiveButton("继续") { _, _ -> host.restorePortableArchive() }
                .setNegativeButton("取消", null)
                .show()
        })
        addView(action("导出完整归档") { host.exportPortableArchive() })
        addView(section("交易导出"))
        addView(LinearLayout(context).apply {
            orientation = HORIZONTAL
            addView(action("导出 CSV") { host.exportTransactions("csv") }, LayoutParams(0, dp(52), 1f))
            addView(action("导出 JSON") { host.exportTransactions("json") }, LayoutParams(0, dp(52), 1f))
        })
        loadFormats()
        showQueue(emptyList())
    }

    fun acceptFiles(files: List<SelectedFile>, skipped: List<QueueItem> = emptyList()) {
        files.forEach { file ->
            val compatible = formats.filter { format -> format.extensions.any { file.name.lowercase().endsWith(it) } }
            if (compatible.isEmpty()) items += QueueItem(file.relativePath, "未处理", "不支持的文件类型")
            else if (file.contentBase64.length > 70_000_000) items += QueueItem(file.relativePath, "未处理", "文件超过 50 MiB")
            else items += QueueItem(file.relativePath, "等待导入", contentBase64 = file.contentBase64, formats = compatible)
        }
        items += skipped
        showQueue(items)
    }

    fun showQueue(files: List<QueueItem>) {
        queue.removeAllViews()
        files.forEach { item ->
            queue.addView(LinearLayout(context).apply {
                orientation = VERTICAL
                setPadding(0, dp(8), 0, dp(8))
                addView(TextView(context).apply { text = "${item.relativePath}\n${item.status}${item.message.takeIf(String::isNotBlank)?.let { " · $it" }.orEmpty()}" })
                if (item.status == "等待导入") {
                    val spinner = Spinner(context).apply {
                        adapter = ArrayAdapter(context, android.R.layout.simple_spinner_dropdown_item, item.formats.map { it.displayName })
                        setSelection(item.formats.indexOfFirst { it.formatId == item.formatId }.coerceAtLeast(0))
                        onItemSelectedListener = SimpleItemSelectedListener { position -> item.formatId = item.formats[position].formatId }
                    }
                    val account = EditText(context).apply {
                        hint = "来源账户，例如：招商银行-尾号1234"
                        setText(item.sourceAccount)
                        minHeight = dp(48)
                        setOnFocusChangeListener { _, focused -> if (!focused) item.sourceAccount = text.toString().trim() }
                    }
                    addView(spinner)
                    addView(account)
                }
            })
        }
        if (files.isEmpty()) queue.addView(TextView(context).apply { text = "尚未选择账单文件"; gravity = Gravity.CENTER; setPadding(0, dp(24), 0, dp(24)) })
        importButton.isEnabled = files.any { it.status == "等待导入" }
    }

    fun showProgress(message: String) {
        progress.text = message
    }

    private fun loadFormats() {
        client.request("GET", "/api/v1/import-formats") { result ->
            result.onSuccess { response ->
                val rows = response.getJSONObject("body").getJSONArray("data")
                formats = (0 until rows.length()).map { index ->
                    val row = rows.getJSONObject(index)
                    val extensions = row.getJSONArray("extensions")
                    ImportFormat(row.getString("format_id"), row.getString("display_name"), (0 until extensions.length()).map(extensions::getString))
                }
            }.onFailure { showProgress(it.message ?: "无法加载账单格式") }
        }
    }

    private fun importNext(index: Int, succeeded: Int, failed: Int) {
        val selected = items.filter { it.status == "等待导入" }
        if (index >= selected.size) {
            showProgress("导入完成：成功 $succeeded 个，未处理 $failed 个")
            importButton.isEnabled = items.any { it.status == "等待导入" }
            return
        }
        val item = selected[index]
        if (item.sourceAccount.isBlank()) {
            item.status = "未处理"; item.message = "请填写来源账户"; showQueue(items)
            importNext(index + 1, succeeded, failed + 1); return
        }
        item.status = "正在导入"; showQueue(items); showProgress("正在处理 ${index + 1}/${selected.size}：${item.relativePath}")
        val body = JSONObject().put("format_id", item.formatId).put("source_account", item.sourceAccount)
            .put("filename", item.relativePath.substringAfterLast('/')).put("content_base64", item.contentBase64)
        client.request("POST", "/api/v1/imports", body) { result ->
            result.onSuccess { item.status = "导入成功"; importNext(index + 1, succeeded + 1, failed) }
                .onFailure { item.status = "未处理"; item.message = it.message ?: "文件内容无法识别"; importNext(index + 1, succeeded, failed + 1) }
            showQueue(items)
        }
    }

    data class SelectedFile(val name: String, val relativePath: String, val contentBase64: String)
    data class ImportFormat(val formatId: String, val displayName: String, val extensions: List<String>)
    data class QueueItem(
        val relativePath: String,
        var status: String,
        var message: String = "",
        val contentBase64: String = "",
        val formats: List<ImportFormat> = emptyList(),
        var formatId: String = formats.firstOrNull()?.formatId.orEmpty(),
        var sourceAccount: String = "",
    )

    private fun section(value: String) = TextView(context).apply {
        text = value
        textSize = 18f
        setTypeface(typeface, Typeface.BOLD)
        setPadding(0, dp(20), 0, dp(8))
    }

    private fun action(label: String, click: () -> Unit) = Button(context).apply {
        text = label
        minHeight = dp(48)
        setOnClickListener { click() }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
