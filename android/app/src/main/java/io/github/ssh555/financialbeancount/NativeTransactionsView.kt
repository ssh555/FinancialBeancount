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
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.ArrayAdapter
import android.widget.TextView
import org.json.JSONObject
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
        addView(LinearLayout(context).apply {
            orientation = HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(TextView(context).apply { text = "交易"; textSize = 26f; setTypeface(typeface, Typeface.BOLD) }, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
            addView(Button(context).apply { text = "回收站"; setOnClickListener { showTrash() } })
            addView(Button(context).apply { text = "记一笔"; setOnClickListener { showEditor(null) } })
        })
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
                    .setPositiveButton("编辑") { _, _ -> showEditor(item) }
                    .setNeutralButton("删除") { _, _ -> confirmDelete(id) }
                    .setNegativeButton("关闭", null).show()
            }.onFailure { AlertDialog.Builder(context).setMessage(it.message ?: "详情加载失败").setPositiveButton("关闭", null).show() }
        }
    }

    private fun showEditor(item: JSONObject?) {
        val fields = LinearLayout(context).apply { orientation = VERTICAL; setPadding(dp(18), 0, dp(18), 0) }
        val date = input("日期 YYYY-MM-DD", item?.optString("booking_date"))
        val amount = input("金额，支出填负数", item?.optString("amount"))
        val merchant = input("商户", item?.optString("merchant"))
        val category = input("分类", item?.optString("category"))
        val notes = input("备注", item?.optString("notes"))
        val direction = Spinner(context).apply {
            adapter = ArrayAdapter(context, android.R.layout.simple_spinner_dropdown_item, listOf("支出", "收入"))
            setSelection(if (item?.optString("direction") == "income") 1 else 0)
        }
        listOf(date, amount, merchant, category, direction, notes).forEach(fields::addView)
        AlertDialog.Builder(context)
            .setTitle(if (item == null) "新增交易" else "编辑交易")
            .setView(ScrollView(context).apply { addView(fields) })
            .setPositiveButton("保存") { _, _ ->
                val selectedDirection = if (direction.selectedItemPosition == 1) "income" else "expense"
                if (item == null) {
                    val body = JSONObject()
                        .put("booking_date", date.text.toString().trim())
                        .put("amount", amount.text.toString().trim())
                        .put("direction", selectedDirection)
                        .put("merchant", merchant.text.toString().trim())
                        .put("category", category.text.toString().trim())
                        .put("notes", notes.text.toString().trim())
                        .put("tx_type", selectedDirection)
                        .put("actor", "android-user")
                    mutate("POST", "/api/v1/transactions", body)
                } else {
                    val changes = JSONObject()
                        .put("booking_date", date.text.toString().trim())
                        .put("amount", amount.text.toString().trim())
                        .put("direction", selectedDirection)
                        .put("merchant", merchant.text.toString().trim())
                        .put("category", category.text.toString().trim())
                        .put("notes", notes.text.toString().trim())
                    mutate("PATCH", "/api/v1/transactions/${item.getString("canonical_id")}", JSONObject().put("actor", "android-user").put("changes", changes))
                }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun confirmDelete(id: String) {
        AlertDialog.Builder(context).setTitle("移入回收站？")
            .setMessage("原始来源和审计记录会保留。")
            .setPositiveButton("删除") { _, _ ->
                mutate("DELETE", "/api/v1/transactions/$id", JSONObject().put("actor", "android-user").put("reason", "user_deleted"))
            }.setNegativeButton("取消", null).show()
    }

    private fun showTrash() {
        client.request("GET", "/api/v1/deleted-transactions?page=1&page_size=200") { result ->
            result.onSuccess { response ->
                val rows = response.getJSONObject("body").getJSONArray("data")
                val content = LinearLayout(context).apply { orientation = VERTICAL; setPadding(dp(12), 0, dp(12), 0) }
                for (index in 0 until rows.length()) {
                    val item = rows.getJSONObject(index)
                    content.addView(Button(context).apply {
                        isAllCaps = false
                        text = "恢复 ${item.optString("merchant", "未命名交易")} · ${money(item.optString("amount", "0"))}"
                        setOnClickListener { mutate("POST", "/api/v1/transactions/${item.getString("canonical_id")}/restore", JSONObject().put("actor", "android-user")) }
                    })
                }
                if (rows.length() == 0) content.addView(message("回收站为空"))
                AlertDialog.Builder(context).setTitle("回收站").setView(ScrollView(context).apply { addView(content) }).setNegativeButton("关闭", null).show()
            }.onFailure { AlertDialog.Builder(context).setMessage(it.message ?: "回收站加载失败").setPositiveButton("关闭", null).show() }
        }
    }

    private fun mutate(method: String, target: String, body: JSONObject) {
        client.request(method, target, body) { result ->
            result.onSuccess { reload() }
                .onFailure { AlertDialog.Builder(context).setMessage(it.message ?: "操作失败").setPositiveButton("关闭", null).show() }
        }
    }

    private fun input(hintText: String, value: String?) = EditText(context).apply {
        hint = hintText
        setText(value.orEmpty())
        minHeight = dp(52)
    }

    private fun message(value: String) = TextView(context).apply { text = value; gravity = Gravity.CENTER; setPadding(0, dp(32), 0, dp(32)) }
    private fun money(value: String) = NumberFormat.getCurrencyInstance(Locale.CHINA).format(value.toBigDecimal())
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
