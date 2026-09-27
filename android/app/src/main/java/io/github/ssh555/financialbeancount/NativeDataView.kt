package io.github.ssh555.financialbeancount

import android.app.AlertDialog
import android.content.Context
import android.graphics.Typeface
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

class NativeDataView(context: Context, private val host: Host) : LinearLayout(context) {
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
    }

    fun showQueue(files: List<QueueItem>) {
        queue.removeAllViews()
        files.forEach { item ->
            queue.addView(TextView(context).apply {
                minHeight = dp(52)
                gravity = Gravity.CENTER_VERTICAL
                text = "${item.relativePath}\n${item.status}${item.message.takeIf(String::isNotBlank)?.let { " · $it" }.orEmpty()}"
            })
        }
        if (files.isEmpty()) queue.addView(TextView(context).apply { text = "尚未选择账单文件"; gravity = Gravity.CENTER; setPadding(0, dp(24), 0, dp(24)) })
    }

    fun showProgress(message: String) {
        progress.text = message
    }

    data class QueueItem(val relativePath: String, val status: String, val message: String = "")

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
