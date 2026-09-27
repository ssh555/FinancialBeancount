package io.github.ssh555.financialbeancount

import android.app.AlertDialog
import android.content.Context
import android.graphics.Typeface
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject

class NativeReviewView(context: Context, private val client: NativeLedgerClient) : LinearLayout(context) {
    private val list = LinearLayout(context)
    private val progress = ProgressBar(context)
    private var reviewType = "imports"

    init {
        orientation = VERTICAL
        setPadding(dp(16), dp(16), dp(16), dp(24))
        addView(TextView(context).apply { text = "待处理"; textSize = 26f; setTypeface(typeface, Typeface.BOLD) })
        addView(HorizontalScrollView(context).apply {
            isHorizontalScrollBarEnabled = false
            addView(LinearLayout(context).apply {
                orientation = HORIZONTAL
                listOf("导入" to "imports", "归并" to "matches", "退款" to "refunds", "分类" to "classifications").forEach { (label, value) ->
                    addView(Button(context).apply { text = label; minHeight = dp(48); setOnClickListener { reviewType = value; reload() } })
                }
            })
        })
        list.orientation = VERTICAL
        addView(list)
        progress.visibility = View.GONE
        addView(progress, LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT).apply { gravity = Gravity.CENTER_HORIZONTAL })
        reload()
    }

    fun reload() {
        list.removeAllViews()
        progress.visibility = View.VISIBLE
        if (reviewType == "imports") loadImportReviews() else loadStandardReviews()
    }

    private fun loadStandardReviews() {
        val route = mapOf("matches" to "candidates", "refunds" to "refunds", "classifications" to "classifications").getValue(reviewType)
        client.request("GET", "/api/v1/review/$route?status=pending&page_size=100") { result ->
            progress.visibility = View.GONE
            result.onSuccess { render(it.getJSONObject("body").getJSONArray("data"), reviewType) }
                .onFailure { showError(it) }
        }
    }

    private fun loadImportReviews() {
        client.request("GET", "/api/v1/import-reviews?status=pending&page_size=100") { sessionsResult ->
            sessionsResult.onFailure { progress.visibility = View.GONE; showError(it) }
            sessionsResult.onSuccess { response ->
                val sessions = response.getJSONObject("body").getJSONArray("data")
                if (sessions.length() == 0) { progress.visibility = View.GONE; render(JSONArray(), "imports"); return@onSuccess }
                val combined = JSONArray()
                var remaining = sessions.length()
                for (index in 0 until sessions.length()) {
                    val sessionId = sessions.getJSONObject(index).getString("session_id")
                    client.request("GET", "/api/v1/import-reviews/$sessionId/items?page_size=200") { itemsResult ->
                        itemsResult.onSuccess { itemsResponse ->
                            val items = itemsResponse.getJSONObject("body").getJSONArray("data")
                            for (itemIndex in 0 until items.length()) {
                                val item = items.getJSONObject(itemIndex)
                                if (item.getString("status") == "pending") combined.put(JSONObject(item.toString()).put("session_id", sessionId))
                            }
                        }
                        remaining -= 1
                        if (remaining == 0) { progress.visibility = View.GONE; render(combined, "imports") }
                    }
                }
            }
        }
    }

    private fun render(rows: JSONArray, type: String) {
        list.removeAllViews()
        if (rows.length() == 0) { list.addView(message("这一类没有待审核项")); return }
        for (index in 0 until rows.length()) {
            val item = rows.getJSONObject(index)
            val endpoint = endpoint(type, item)
            list.addView(LinearLayout(context).apply {
                orientation = VERTICAL
                setPadding(0, dp(10), 0, dp(10))
                addView(Button(context).apply {
                    isAllCaps = false
                    gravity = Gravity.START
                    text = "${title(type, item)}\n${subtitle(type, item)}"
                    setOnClickListener { AlertDialog.Builder(context).setTitle(title(type, item)).setMessage(item.toString(2)).setPositiveButton("关闭", null).show() }
                })
                addView(LinearLayout(context).apply {
                    orientation = HORIZONTAL
                    addView(Button(context).apply { text = "拒绝"; setOnClickListener { decide(endpoint, "reject") } }, LayoutParams(0, dp(48), 1f))
                    addView(Button(context).apply { text = "确认"; setOnClickListener { decide(endpoint, "confirm") } }, LayoutParams(0, dp(48), 1f))
                })
            })
        }
    }

    private fun decide(endpoint: String, action: String) {
        AlertDialog.Builder(context).setMessage(if (action == "confirm") "确认这项审核决定？" else "拒绝这项建议？")
            .setPositiveButton("继续") { _, _ ->
                client.request("POST", "$endpoint/$action", JSONObject().put("actor", "android-user")) { result ->
                    result.onSuccess { reload() }.onFailure { showError(it) }
                }
            }.setNegativeButton("取消", null).show()
    }

    private fun endpoint(type: String, item: JSONObject): String = when (type) {
        "imports" -> "/api/v1/import-reviews/${item.getString("session_id")}/items/${item.getString("review_item_id")}"
        "matches" -> "/api/v1/review/candidates/${item.getString("candidate_id")}"
        "refunds" -> "/api/v1/review/refunds/${item.getString("relationship_id")}"
        else -> "/api/v1/review/classifications/${item.getString("candidate_id")}"
    }

    private fun title(type: String, item: JSONObject): String {
        val source = when (type) { "imports" -> item.optJSONObject("raw"); "matches" -> item.optJSONObject("payment"); "refunds" -> item.optJSONObject("refund"); else -> item.optJSONObject("transaction") }
        return source?.optString("merchant")?.takeIf { it.isNotBlank() } ?: source?.optString("counterparty")?.takeIf { it.isNotBlank() } ?: "未命名交易"
    }

    private fun subtitle(type: String, item: JSONObject) = when (type) {
        "imports" -> item.optString("item_type", "导入变化")
        "matches", "refunds" -> "置信度 ${item.optString("confidence", "-")}"
        else -> "建议 ${item.optString("proposed_type", "-")} / ${item.optString("proposed_category", "未分类")}"
    }

    private fun showError(error: Throwable) { list.removeAllViews(); list.addView(message(error.message ?: "审核加载失败")) }
    private fun message(value: String) = TextView(context).apply { text = value; gravity = Gravity.CENTER; setPadding(0, dp(32), 0, dp(32)) }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
