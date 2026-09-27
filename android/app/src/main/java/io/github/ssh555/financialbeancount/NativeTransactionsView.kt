package io.github.ssh555.financialbeancount

import android.content.Context
import android.content.DialogInterface
import android.graphics.Typeface
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.ArrayAdapter
import android.widget.TextView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.card.MaterialCardView
import com.google.android.material.button.MaterialButton
import com.google.android.material.textfield.MaterialAutoCompleteTextView
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout
import org.json.JSONObject
import java.net.URLEncoder
import java.text.NumberFormat
import java.util.Locale

class NativeTransactionsView(context: Context, private val client: NativeLedgerClient) : LinearLayout(context) {
    private val search = EditText(context)
    private val list = LinearLayout(context)
    private val progress = ProgressBar(context)
    private val more = MaterialButton(context)
    private var page = 1
    private var loaded = 0
    private val sourceFilter = SourceFilterButton(context, client) { reload() }

    init {
        orientation = VERTICAL
        setPadding(dp(16), dp(16), dp(16), dp(24))
        addView(TextView(context).apply { text = "交易"; textSize = 26f; setTypeface(typeface, Typeface.BOLD) })
        addView(LinearLayout(context).apply {
            orientation = HORIZONTAL
            setPadding(0, dp(6), 0, dp(6))
            addView(MaterialButton(context).apply { text = "回收站"; insetTop = 0; insetBottom = 0; setOnClickListener { showTrash() } }, LayoutParams(0, dp(48), 1f).apply { marginEnd = dp(5) })
            addView(MaterialButton(context).apply { text = "记一笔"; insetTop = 0; insetBottom = 0; tag = "primary"; NativeUi.styleButton(this, primary = true); setOnClickListener { showEditor(null) } }, LayoutParams(0, dp(48), 1f).apply { marginStart = dp(5) })
        })
        addView(sourceFilter)
        addView(LinearLayout(context).apply {
            orientation = HORIZONTAL
            setPadding(0, dp(6), 0, dp(10))
            search.hint = "搜索商户、备注"
            search.isSingleLine = true
            addView(search, LayoutParams(0, dp(52), 1f))
            addView(MaterialButton(context).apply { text = "搜索"; insetTop = 0; insetBottom = 0; minHeight = dp(48); setOnClickListener { reload() } })
        })
        list.orientation = VERTICAL
        addView(list)
        progress.visibility = View.GONE
        addView(progress, LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT).apply { gravity = Gravity.CENTER_HORIZONTAL })
        more.text = "加载更多"
        more.minHeight = dp(48)
        more.setOnClickListener { page += 1; loadPage(false) }
        addView(more)
    }

    fun reload() { page = 1; loaded = 0; list.removeAllViews(); loadPage(true) }

    private fun loadPage(reset: Boolean) {
        progress.visibility = View.VISIBLE
        more.isEnabled = false
        val query = URLEncoder.encode(search.text.toString().trim(), "UTF-8")
        val sources = sourceFilter.query().let { if (it.isBlank()) "" else "&$it" }
        client.request("GET", "/api/v1/transactions?page=$page&page_size=30&search=$query$sources") { result ->
            progress.visibility = View.GONE
            result.onSuccess { response ->
                val body = response.getJSONObject("body")
                val rows = body.getJSONArray("data")
                val total = body.getJSONObject("meta").getInt("total")
                if (reset && rows.length() == 0) list.addView(message("没有符合条件的交易"))
                for (index in 0 until rows.length()) {
                    val item = rows.getJSONObject(index)
                    list.addView(transactionCard(item))
                }
                loaded += rows.length()
                more.visibility = if (loaded < total) View.VISIBLE else View.GONE
                more.isEnabled = true
                NativeUi.styleTree(list)
            }.onFailure { if (reset) list.addView(message(it.message ?: "交易加载失败")); more.isEnabled = true }
        }
    }

    private fun showDetail(id: String) {
        client.request("GET", "/api/v1/transactions/$id") { result ->
            result.onSuccess { response ->
                val item = response.getJSONObject("body").getJSONObject("data")
                val details = LinearLayout(context).apply {
                    orientation = VERTICAL
                    setPadding(dp(24), dp(4), dp(24), dp(4))
                    addView(detailRow("金额", money(item.optString("amount", "0")), featured = true))
                    addView(detailRow("日期", item.optString("booking_date", "—")))
                    addView(detailRow("分类", item.optString("category", "未分类").ifBlank { "未分类" }))
                    addView(detailRow("备注", item.optString("notes", "").ifBlank { "无" }))
                }
                MaterialAlertDialogBuilder(context).setTitle(item.optString("merchant", "交易详情"))
                    .setView(details)
                    .setPositiveButton("编辑") { _, _ -> showEditor(item) }
                    .setNeutralButton("删除") { _, _ -> confirmDelete(id) }
                    .setNegativeButton("关闭", null).show()
            }.onFailure { showErrorDialog(it.message ?: "详情加载失败") }
        }
    }

    private fun showEditor(item: JSONObject?) {
        val fields = LinearLayout(context).apply { orientation = VERTICAL; setPadding(dp(20), 0, dp(20), dp(8)) }
        val date = input("交易日期", item?.optString("booking_date"), InputType.TYPE_CLASS_DATETIME)
        date.layout.helperText = "格式：YYYY-MM-DD"
        val amount = input("金额", item?.optString("amount"), InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL or InputType.TYPE_NUMBER_FLAG_SIGNED)
        val merchant = input("商户", item?.optString("merchant"))
        val category = input("分类", item?.optString("category"))
        val notes = input("备注（可选）", item?.optString("notes"), InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES)
        val direction = MaterialAutoCompleteTextView(context).apply {
            setAdapter(ArrayAdapter(context, android.R.layout.simple_dropdown_item_1line, listOf("支出", "收入")))
            setText(if (item?.optString("direction") == "income") "收入" else "支出", false)
        }
        val directionLayout = TextInputLayout(context).apply {
            hint = "收支类型"
            endIconMode = TextInputLayout.END_ICON_DROPDOWN_MENU
            addView(direction, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))
        }
        listOf(date.layout, amount.layout, directionLayout, merchant.layout, category.layout, notes.layout).forEach {
            fields.addView(it, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT).apply { setMargins(0, dp(5), 0, dp(5)) })
        }
        val dialog = MaterialAlertDialogBuilder(context)
            .setTitle(if (item == null) "新增交易" else "编辑交易")
            .setView(ScrollView(context).apply { addView(fields) })
            .setPositiveButton("保存", null)
            .setNegativeButton("取消", null)
            .create()
        dialog.setOnShowListener {
            dialog.getButton(DialogInterface.BUTTON_POSITIVE).setOnClickListener {
                date.layout.error = null; amount.layout.error = null; merchant.layout.error = null
                val dateValue = date.input.text.toString().trim()
                val amountValue = amount.input.text.toString().trim()
                val merchantValue = merchant.input.text.toString().trim()
                val validDate = runCatching { java.time.LocalDate.parse(dateValue) }.isSuccess
                val validAmount = amountValue.toBigDecimalOrNull()?.compareTo(java.math.BigDecimal.ZERO) != 0 && amountValue.toBigDecimalOrNull() != null
                if (!validDate) date.layout.error = "请输入有效日期，例如 2026-09-27"
                if (!validAmount) amount.layout.error = "请输入非零金额"
                if (merchantValue.isBlank()) merchant.layout.error = "请填写商户或交易对象"
                if (!validDate || !validAmount || merchantValue.isBlank()) return@setOnClickListener
                val selectedDirection = if (direction.text.toString() == "收入") "income" else "expense"
                if (item == null) {
                    val body = JSONObject()
                        .put("booking_date", dateValue)
                        .put("amount", amountValue)
                        .put("direction", selectedDirection)
                        .put("merchant", merchantValue)
                        .put("category", category.input.text.toString().trim())
                        .put("notes", notes.input.text.toString().trim())
                        .put("tx_type", selectedDirection)
                        .put("actor", "android-user")
                    mutate("POST", "/api/v1/transactions", body)
                } else {
                    val changes = JSONObject()
                        .put("booking_date", dateValue)
                        .put("amount", amountValue)
                        .put("direction", selectedDirection)
                        .put("merchant", merchantValue)
                        .put("category", category.input.text.toString().trim())
                        .put("notes", notes.input.text.toString().trim())
                    mutate("PATCH", "/api/v1/transactions/${item.getString("canonical_id")}", JSONObject().put("actor", "android-user").put("changes", changes))
                }
                dialog.dismiss()
            }
        }
        dialog.show()
    }

    private fun confirmDelete(id: String) {
        MaterialAlertDialogBuilder(context).setTitle("移入回收站？")
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
                MaterialAlertDialogBuilder(context).setTitle("回收站").setView(ScrollView(context).apply { addView(content) }).setNegativeButton("关闭", null).show()
            }.onFailure { showErrorDialog(it.message ?: "回收站加载失败") }
        }
    }

    private fun mutate(method: String, target: String, body: JSONObject) {
        client.request(method, target, body) { result ->
            result.onSuccess { reload() }
                .onFailure { showErrorDialog(it.message ?: "操作失败") }
        }
    }

    private data class InputField(val layout: TextInputLayout, val input: TextInputEditText)

    private fun input(label: String, value: String?, inputType: Int = InputType.TYPE_CLASS_TEXT): InputField {
        val input = TextInputEditText(context).apply {
            setText(value.orEmpty())
            this.inputType = inputType
            isSingleLine = label != "备注（可选）"
        }
        return InputField(TextInputLayout(context).apply {
            hint = label
            boxBackgroundMode = TextInputLayout.BOX_BACKGROUND_OUTLINE
            addView(input, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))
        }, input)
    }

    private fun detailRow(label: String, value: String, featured: Boolean = false) = TextView(context).apply {
        text = "$label\n$value"
        textSize = if (featured) 20f else 15f
        setTypeface(typeface, if (featured) Typeface.BOLD else Typeface.NORMAL)
        setPadding(0, dp(9), 0, dp(9))
    }

    private fun transactionCard(item: JSONObject) = MaterialCardView(context).apply {
        radius = dp(16).toFloat()
        cardElevation = dp(1).toFloat()
        strokeWidth = dp(1)
        setStrokeColor(NativeUi.line)
        setCardBackgroundColor(NativeUi.card)
        isClickable = true
        isFocusable = true
        contentDescription = "打开 ${item.optString("merchant", "未命名交易")} 的交易详情"
        setOnClickListener { showDetail(item.getString("canonical_id")) }
        addView(LinearLayout(context).apply {
            orientation = VERTICAL
            setPadding(dp(16), dp(14), dp(16), dp(14))
            addView(LinearLayout(context).apply {
                orientation = HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                addView(TextView(context).apply {
                    text = item.optString("merchant", "未命名交易").ifBlank { "未命名交易" }
                    textSize = 16f
                    setTypeface(typeface, Typeface.BOLD)
                    maxLines = 1
                }, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
                addView(TextView(context).apply {
                    text = money(item.getString("amount"))
                    textSize = 16f
                    setTypeface(typeface, Typeface.BOLD)
                    setTextColor(if (item.optString("direction") == "income") NativeUi.green else NativeUi.ink)
                })
            })
            addView(TextView(context).apply {
                text = "${item.getString("booking_date")} · ${item.optString("category", "未分类").ifBlank { "未分类" }}"
                textSize = 13f
                setTextColor(NativeUi.muted)
                setPadding(0, dp(7), 0, 0)
            })
        })
        layoutParams = LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT).apply {
            setMargins(0, dp(5), 0, dp(5))
        }
    }

    private fun showErrorDialog(message: String) = MaterialAlertDialogBuilder(context)
        .setTitle("未能完成操作").setMessage(message).setPositiveButton("知道了", null).show()

    private fun message(value: String) = TextView(context).apply { text = value; gravity = Gravity.CENTER; setPadding(0, dp(32), 0, dp(32)) }
    private fun money(value: String) = NumberFormat.getCurrencyInstance(Locale.CHINA).format(value.toBigDecimal())
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
