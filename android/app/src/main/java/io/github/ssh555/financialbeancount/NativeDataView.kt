package io.github.ssh555.financialbeancount

import android.content.Context
import android.graphics.Typeface
import android.text.Editable
import android.text.TextWatcher
import android.text.util.Linkify
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ArrayAdapter
import android.widget.TextView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.card.MaterialCardView
import com.google.android.material.textfield.MaterialAutoCompleteTextView
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout
import org.json.JSONObject

class NativeDataView(context: Context, private val client: NativeLedgerClient, private val host: Host) : LinearLayout(context) {
    interface Host {
        fun pickOneStatement()
        fun pickMultipleStatements()
        fun pickStatementFolder()
        fun restorePortableArchive()
        fun exportTransactions(format: String)
        fun exportPortableArchive()
        fun checkForUpdates()
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
        addView(TextView(context).apply { text = "导入、备份和设备设置"; setTextColor(NativeUi.muted); setPadding(0, 0, 0, dp(10)) })
        addView(action("导入官方账单") { showImportMenu() })
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
        addView(action("备份与恢复") { showArchiveMenu() })
        addView(action("导出交易") { showExportMenu() })
        addView(action("更新与关于") { showAbout() })
        addView(section("数据安全"))
        addView(action("删除所有数据") { confirmDeleteAll() })
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
        queue.visibility = if (files.isEmpty()) GONE else VISIBLE
        importButton.visibility = if (files.isEmpty()) GONE else VISIBLE
        files.forEach { item ->
            queue.addView(LinearLayout(context).apply {
                orientation = VERTICAL
                setPadding(dp(14), dp(12), dp(14), dp(12))
                NativeUi.card(this, 14)
                addView(TextView(context).apply { text = "${item.relativePath}\n${item.status}${item.message.takeIf(String::isNotBlank)?.let { " · $it" }.orEmpty()}" })
                if (item.status == "等待导入") {
                    val formatNames = item.formats.map { it.displayName }
                    val format = MaterialAutoCompleteTextView(context).apply {
                        setAdapter(ArrayAdapter(context, android.R.layout.simple_dropdown_item_1line, formatNames))
                        val initial = item.formats.indexOfFirst { it.formatId == item.formatId }.coerceAtLeast(0)
                        setText(formatNames.getOrElse(initial) { "自动识别" }, false)
                        setOnItemClickListener { _, _, position, _ -> item.formatId = item.formats[position].formatId }
                    }
                    val formatLayout = TextInputLayout(context).apply {
                        hint = "账单格式"
                        endIconMode = TextInputLayout.END_ICON_DROPDOWN_MENU
                        addView(format, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))
                    }
                    val account = TextInputEditText(context).apply {
                        setText(item.sourceAccount)
                        addTextChangedListener(object : TextWatcher {
                            override fun beforeTextChanged(value: CharSequence?, start: Int, count: Int, after: Int) = Unit
                            override fun onTextChanged(value: CharSequence?, start: Int, before: Int, count: Int) {
                                item.sourceAccount = value?.toString()?.trim().orEmpty()
                            }
                            override fun afterTextChanged(value: Editable?) = Unit
                        })
                    }
                    val accountLayout = TextInputLayout(context).apply {
                        hint = "来源账户"
                        helperText = "例如：招商银行-尾号 1234"
                        boxBackgroundMode = TextInputLayout.BOX_BACKGROUND_OUTLINE
                        addView(account, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))
                    }
                    addView(formatLayout, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT).apply { setMargins(0, dp(8), 0, dp(4)) })
                    addView(accountLayout, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT).apply { setMargins(0, dp(4), 0, 0) })
                }
            })
        }
        importButton.isEnabled = files.any { it.status == "等待导入" }
        NativeUi.styleTree(queue)
    }

    fun showProgress(message: String) {
        progress.text = message
    }

    private fun showImportMenu() {
        MaterialAlertDialogBuilder(context)
            .setTitle("导入官方账单")
            .setItems(arrayOf("选择一个文件", "选择多个文件", "选择文件夹")) { _, index ->
                when (index) {
                    0 -> host.pickOneStatement()
                    1 -> host.pickMultipleStatements()
                    else -> host.pickStatementFolder()
                }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun showArchiveMenu() {
        MaterialAlertDialogBuilder(context)
            .setTitle("备份与恢复")
            .setItems(arrayOf("导出完整归档", "从完整归档恢复")) { _, index ->
                if (index == 0) host.exportPortableArchive() else confirmArchiveRestore()
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun confirmArchiveRestore() {
        MaterialAlertDialogBuilder(context)
            .setTitle("覆盖当前账本？")
            .setMessage("请先导出备份。恢复成功后，当前设备账本会被完整归档替换。")
            .setPositiveButton("继续") { _, _ -> host.restorePortableArchive() }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun showExportMenu() {
        MaterialAlertDialogBuilder(context)
            .setTitle("导出交易")
            .setItems(arrayOf("CSV 表格", "JSON 数据")) { _, index -> host.exportTransactions(if (index == 0) "csv" else "json") }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun showAbout() {
        val about = TextView(context).apply {
            text = "FinancialBeancount\n版本 ${BuildConfig.VERSION_NAME}\n\n作者 GitHub：https://github.com/ssh555\n项目仓库：https://github.com/ssh555/FinancialBeancount\n原始出处：https://github.com/CacinieP/FinancialBeancount\n许可证：MIT"
            setPadding(dp(20), dp(8), dp(20), dp(8))
            autoLinkMask = Linkify.WEB_URLS
        }
        MaterialAlertDialogBuilder(context)
            .setTitle("更新与关于")
            .setView(about)
            .setPositiveButton("检查更新") { _, _ -> host.checkForUpdates() }
            .setNegativeButton("关闭", null)
            .show()
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

    private fun confirmDeleteAll() {
        MaterialAlertDialogBuilder(context)
            .setTitle("永久删除所有数据？")
            .setMessage("请先导出完整归档。此操作会删除账单、原始导入记录和审核记录，且无法撤销。")
            .setPositiveButton("继续") { _, _ ->
                MaterialAlertDialogBuilder(context)
                    .setTitle("再次确认")
                    .setMessage("删除后本设备账本将恢复为空状态。")
                    .setPositiveButton("永久删除") { _, _ -> deleteAll() }
                    .setNegativeButton("取消", null)
                    .show()
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun deleteAll() {
        client.request("DELETE", "/api/v1/data", JSONObject().put("confirmation", "DELETE ALL DATA")) { result ->
            result.onSuccess {
                items.clear()
                showQueue(emptyList())
                showProgress("全部数据已删除，账本已恢复为空状态")
            }.onFailure { showProgress(it.message ?: "删除失败") }
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
        setPadding(dp(2), dp(22), 0, dp(8))
    }

    private fun action(label: String, click: () -> Unit) = MaterialCardView(context).apply {
        val descriptions = mapOf(
            "选择一个文件" to "导入一份微信、支付宝或银行账单",
            "选择多个文件" to "一次加入多份账单并逐项查看结果",
            "选择文件夹" to "扫描所选文件夹中的支持格式",
            "导入官方账单" to "单个、多个或整个文件夹",
            "备份与恢复" to "导出或恢复完整账本归档",
            "导出交易" to "生成 CSV 表格或 JSON 数据",
            "更新与关于" to "检查新版本、项目来源与许可证",
            "恢复完整归档" to "用本地归档覆盖并恢复当前账本",
            "导出完整归档" to "备份账本、原始记录和审核轨迹",
            "检查更新" to "仅在点击后连接 GitHub 检查新版",
            "删除所有数据" to "永久清空本设备账本，不删除应用",
        )
        radius = dp(16).toFloat()
        cardElevation = dp(1).toFloat()
        strokeWidth = dp(1)
        setStrokeColor(NativeUi.line)
        setCardBackgroundColor(NativeUi.card)
        isClickable = true
        isFocusable = true
        contentDescription = label
        setOnClickListener { click() }
        addView(TextView(context).apply {
            text = descriptions[label]?.let { "$label  ›\n$it" } ?: label
            gravity = Gravity.START or Gravity.CENTER_VERTICAL
            textSize = 15f
            setPadding(dp(16), dp(13), dp(16), dp(13))
            if (descriptions.containsKey(label)) minimumHeight = dp(72)
        })
        layoutParams = LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT).apply { setMargins(0, dp(5), 0, dp(5)) }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
