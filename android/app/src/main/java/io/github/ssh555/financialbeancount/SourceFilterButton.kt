package io.github.ssh555.financialbeancount

import android.content.Context
import android.widget.Button
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import org.json.JSONArray
import java.net.URLEncoder

class SourceFilterButton(
    context: Context,
    private val client: NativeLedgerClient,
    private val changed: () -> Unit,
) : Button(context) {
    private val selected = linkedSetOf<String>()

    init {
        text = "来源：全部"
        isAllCaps = false
        minHeight = dp(48)
        setOnClickListener { loadAndShow() }
    }

    fun query(): String = selected.joinToString("&") {
        "source=${URLEncoder.encode(it, "UTF-8")}"
    }

    private fun loadAndShow() {
        client.request("GET", "/api/v1/sources") { result ->
            result.onSuccess { response -> show(response.getJSONObject("body").getJSONArray("data")) }
                .onFailure { MaterialAlertDialogBuilder(context).setTitle("来源加载失败").setMessage(it.message ?: "请稍后重试").setPositiveButton("知道了", null).show() }
        }
    }

    private fun show(rows: JSONArray) {
        val labels = mutableListOf<String>()
        val values = mutableListOf<String>()
        val platformNames = mapOf("alipay" to "支付宝", "wechat" to "微信", "bank" to "银行", "unionpay" to "云闪付")
        val platforms = mutableSetOf<String>()
        for (index in 0 until rows.length()) {
            val item = rows.getJSONObject(index)
            val source = item.getString("source")
            if (platforms.add(source)) {
                labels += "${platformNames[source] ?: source}（全部账户）"
                values += source
            }
            labels += "  ${item.getString("source_account")} · ${item.getInt("transaction_count")} 笔"
            values += "$source::${item.getString("source_account")}" 
        }
        val checked = BooleanArray(values.size) { values[it] in selected }
        MaterialAlertDialogBuilder(context)
            .setTitle("选择来源（可多选）")
            .setMultiChoiceItems(labels.toTypedArray(), checked) { _, index, value -> checked[index] = value }
            .setNeutralButton("清除") { _, _ -> selected.clear(); update() }
            .setPositiveButton("应用") { _, _ ->
                selected.clear()
                values.forEachIndexed { index, value -> if (checked[index]) selected += value }
                update()
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun update() {
        text = if (selected.isEmpty()) "来源：全部" else "来源：已选 ${selected.size} 项"
        changed()
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
