package io.github.ssh555.financialbeancount

import android.app.AlertDialog
import android.content.Context
import android.graphics.Typeface
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import java.net.URLEncoder
import java.text.NumberFormat
import java.util.Locale

class NativeTransactionsView(context: Context, private val client: NativeLedgerClient) : LinearLayout(context) {
    private val search = EditText(context)
    private val list = LinearLayout(context)
    private val progress = ProgressBar(context)
    private val more = Button(context)
    private var page = 1
    private var loaded = 0

    init {
        orientation = VERTICAL
        setPadding(dp(16), dp(16), dp(16), dp(24))
        addView(TextView(context).apply { text = "交易"; textSize = 26f; setTypeface(typeface, Typeface.BOLD) })
        addView(LinearLayout(context).apply {
            orientation = HORIZONTAL
            search.hint = "搜索商户、备注"
            search.isSingleLine = true
            addView(search, LayoutParams(0, dp(52), 1f))
            addView(Button(context).apply { text = "搜索"; minHeight = dp(48); setOnClickListener { reload() } })
        })
        list.orientation = VERTICAL
        addView(list)
        progress.visibility = View.GONE
        addView(progress, LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT).apply { gravity = Gravity.CENTER_HORIZONTAL })
        more.text = "加载更多"
        more.minHeight = dp(48)
        more.setOnClickListener { page += 1; loadPage(false) }
        addView(more)
        reload()
    }

    fun reload() { page = 1; loaded = 0; list.removeAllViews(); loadPage(true) }

    private fun loadPage(reset: Boolean) {
        progress.visibility = View.VISIBLE
        more.isEnabled = false
        val query = URLEncoder.encode(search.text.toString().trim(), "UTF-8")
        client.request("GET", "/api/v1/transactions?page=$page&page_size=30&search=$query") { result ->
            progress.visibility = View.GONE
            result.onSuccess { response ->
                val body = response.getJSONObject("body")
                val rows = body.getJSONArray("data")
                val total = body.getJSONObject("meta").getInt("total")
                if (reset && rows.length() == 0) list.addView(message("没有符合条件的交易"))
                for (index in 0 until rows.length()) {
                    val item = rows.getJSONObject(index)
                    list.addView(Button(context).apply {
                        isAllCaps = false
                        minHeight = dp(64)
                        gravity = Gravity.START or Gravity.CENTER_VERTICAL
                        text = "${item.optString("merchant", "未命名交易")}   ${money(item.getString("amount"))}\n${item.getString("booking_date")} · ${item.optString("category", "未分类")}"
                        setOnClickListener { showDetail(item.getString("canonical_id")) }
                    })
                }
                loaded += rows.length()
                more.visibility = if (loaded < total) View.VISIBLE else View.GONE
                more.isEnabled = true
            }.onFailure { if (reset) list.addView(message(it.message ?: "交易加载失败")); more.isEnabled = true }
        }
    }

    private fun showDetail(id: String) {
        client.request("GET", "/api/v1/transactions/$id") { result ->
            result.onSuccess { response ->
                val item = response.getJSONObject("body").getJSONObject("data")
                AlertDialog.Builder(context).setTitle(item.optString("merchant", "交易详情"))
                    .setMessage("日期：${item.optString("booking_date")}\n金额：${money(item.optString("amount", "0"))}\n分类：${item.optString("category", "未分类")}\n备注：${item.optString("notes", "")}")
                    .setPositiveButton("关闭", null).show()
            }.onFailure { AlertDialog.Builder(context).setMessage(it.message ?: "详情加载失败").setPositiveButton("关闭", null).show() }
        }
    }

    private fun message(value: String) = TextView(context).apply { text = value; gravity = Gravity.CENTER; setPadding(0, dp(32), 0, dp(32)) }
    private fun money(value: String) = NumberFormat.getCurrencyInstance(Locale.CHINA).format(value.toBigDecimal())
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
