package io.github.ssh555.financialbeancount

import android.app.AlertDialog
import android.content.Context
import android.graphics.Typeface
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject

class NativeReviewView(context: Context, private val client: NativeLedgerClient) : LinearLayout(context) {
    private val list = LinearLayout(context)
    private val progress = ProgressBar(context)
    private var reviewType = "imports"
    private val selectedWarnings = mutableSetOf<String>()
    private val warningChecks = mutableListOf<CheckBox>()

    init {
        orientation = VERTICAL
        setPadding(dp(16), dp(16), dp(16), dp(24))
        addView(TextView(context).apply { text = "待处理"; textSize = 26f; setTypeface(typeface, Typeface.BOLD) })
        addView(TextView(context).apply { text = "优先处理必须项：确认并入、修正并入、关联/合并、保留独立、排除，或暂缓。" })
        addView(LinearLayout(context).apply {
            orientation = VERTICAL
            val choices = listOf("导入" to "imports", "归并" to "matches", "退款" to "refunds", "分类" to "classifications", "警告" to "warnings", "已通过" to "acknowledged")
            choices.chunked(3).forEach { rowChoices ->
                addView(LinearLayout(context).apply {
                    orientation = HORIZONTAL
                    rowChoices.forEach { (label, value) ->
                        addView(Button(context).apply {
                            text = label
                            minWidth = 0
                            minHeight = dp(44)
                            setOnClickListener { reviewType = value; reload() }
                        }, LayoutParams(0, dp(48), 1f))
                    }
                })
            }
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
        val route = mapOf("matches" to "candidates", "refunds" to "refunds", "classifications" to "classifications", "warnings" to "refunds", "acknowledged" to "refunds").getValue(reviewType)
        val query = when (reviewType) { "warnings" -> "attention=warning"; "acknowledged" -> "attention=acknowledged"; else -> "status=pending" }
        client.request("GET", "/api/v1/review/$route?$query&page_size=100") { result ->
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
        selectedWarnings.clear()
        warningChecks.clear()
        if (rows.length() == 0) { list.addView(message("这一类没有待审核项")); NativeUi.styleTree(list); return }
        if (type == "warnings" || type == "acknowledged") {
            list.addView(LinearLayout(context).apply {
                orientation = HORIZONTAL
                addView(Button(context).apply {
                    text = "全选"
                    setOnClickListener {
                        warningChecks.forEach { it.isChecked = true }
                    }
                }, LayoutParams(0, dp(48), 1f))
                if (type == "warnings") {
                    addView(Button(context).apply { text = "不通过"; setOnClickListener { resolveWarnings("escalate") } }, LayoutParams(0, dp(48), 1f))
                    addView(Button(context).apply { text = "批量通过"; setOnClickListener { resolveWarnings("acknowledge") } }, LayoutParams(0, dp(48), 1f))
                } else addView(Button(context).apply { text = "恢复 Warning"; setOnClickListener { resolveWarnings("restore") } }, LayoutParams(0, dp(48), 2f))
            })
        }
        for (index in 0 until rows.length()) {
            val item = rows.getJSONObject(index)
            val endpoint = endpoint(type, item)
            list.addView(LinearLayout(context).apply {
                orientation = VERTICAL
                setPadding(0, dp(10), 0, dp(10))
                if (type == "warnings" || type == "acknowledged") addView(CheckBox(context).apply {
                    val relationshipId = item.getString("relationship_id")
                    text = "选择此项"
                    isChecked = selectedWarnings.contains(relationshipId)
                    setOnCheckedChangeListener { _, checked -> if (checked) selectedWarnings.add(relationshipId) else selectedWarnings.remove(relationshipId) }
                    warningChecks.add(this)
                })
                addView(Button(context).apply {
                    isAllCaps = false
                    gravity = Gravity.START
                    text = "${title(type, item)}\n${subtitle(type, item)}"
                    setOnClickListener { showDetail(type, item, endpoint) }
                })
            })
        }
        NativeUi.styleTree(list)
    }

    private fun showDetail(type: String, item: JSONObject, endpoint: String) {
        val builder = AlertDialog.Builder(context)
            .setTitle(title(type, item))
            .setMessage(item.toString(2))
            .setNegativeButton("关闭", null)
        if (type != "warnings" && type != "acknowledged") {
            builder.setPositiveButton(if (type == "matches" || type == "refunds") "关联/合并" else "确认并入") { _, _ -> decide(endpoint, "confirm") }
            builder.setNeutralButton("更多处理") { _, _ -> showMoreActions(type, item, endpoint) }
        }
        builder.show()
    }

    private fun showMoreActions(type: String, item: JSONObject, endpoint: String) {
        val preserveLabel = when (type) {
            "matches", "refunds" -> "保留为独立交易"
            "classifications" -> "保留原分类"
            else -> "排除此项"
        }
        AlertDialog.Builder(context)
            .setTitle("选择处理方式")
            .setItems(arrayOf("修正信息", preserveLabel, "暂缓处理")) { dialog, index ->
                when (index) {
                    0 -> if (type == "imports" || type == "matches") showModify(type, item, endpoint) else showCanonicalEdit(type, item, endpoint)
                    1 -> decide(endpoint, "reject")
                    else -> dialog.dismiss()
                }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun showModify(type: String, item: JSONObject, endpoint: String) {
        val source = if (type == "imports") item.optJSONObject("raw") else item.optJSONObject("payment")
        val fields = LinearLayout(context).apply { orientation = VERTICAL; setPadding(dp(18), 0, dp(18), 0) }
        val merchantValue = source?.optString("merchant")?.takeIf { it.isNotBlank() }
            ?: source?.optString("counterparty")
        val merchant = edit("商户", merchantValue)
        val category = edit("分类", source?.optString("category"))
        val notes = edit("备注", source?.optString("notes"))
        listOf(merchant, category, notes).forEach(fields::addView)
        AlertDialog.Builder(context)
            .setTitle("人工修改并完成审核")
            .setView(fields)
            .setPositiveButton("保存") { _, _ ->
                val changes = JSONObject()
                    .put("merchant", merchant.text.toString().trim())
                    .put("category", category.text.toString().trim())
                    .put("notes", notes.text.toString().trim())
                val action = if (type == "imports") "modify" else "confirm"
                client.request(
                    "POST",
                    "$endpoint/$action",
                    JSONObject().put("actor", "android-user").put("changes", changes),
                ) { result ->
                    result.onSuccess { reload() }.onFailure { showError(it) }
                }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun showCanonicalEdit(type: String, item: JSONObject, reviewEndpoint: String) {
        val source = if (type == "refunds") item.getJSONObject("refund") else item.getJSONObject("transaction")
        val canonicalId = source.getString("canonical_id")
        val fields = LinearLayout(context).apply { orientation = VERTICAL; setPadding(dp(18), 0, dp(18), 0) }
        val merchant = edit("商户", source.optString("merchant"))
        val category = edit("分类", source.optString("category"))
        val notes = edit("备注", source.optString("notes"))
        listOf(merchant, category, notes).forEach(fields::addView)
        AlertDialog.Builder(context)
            .setTitle("修正并入或排除")
            .setView(fields)
            .setPositiveButton("保存修正") { _, _ ->
                val changes = JSONObject().put("merchant", merchant.text.toString().trim())
                    .put("category", category.text.toString().trim()).put("notes", notes.text.toString().trim())
                client.request("PATCH", "/api/v1/transactions/$canonicalId", JSONObject().put("actor", "android-user").put("changes", changes)) { result ->
                    result.onSuccess { reload() }.onFailure { showError(it) }
                }
            }
            .setNeutralButton("排除") { _, _ -> confirmExclusion(reviewEndpoint) }
            .setNegativeButton("暂缓", null)
            .show()
    }

    private fun confirmExclusion(reviewEndpoint: String) {
        AlertDialog.Builder(context).setMessage("确认排除此账单？原始导入证据仍会保留，可从已删除记录恢复。")
            .setPositiveButton("确认排除") { _, _ ->
                client.request("POST", "$reviewEndpoint/exclude", JSONObject().put("actor", "android-user").put("reason", "人工审核排除")) { result ->
                    result.onSuccess { reload() }.onFailure { showError(it) }
                }
            }.setNegativeButton("取消", null).show()
    }

    private fun decide(endpoint: String, action: String) {
        AlertDialog.Builder(context).setMessage(if (action == "confirm") "确认这项审核决定？" else "拒绝这项建议？")
            .setPositiveButton("继续") { _, _ ->
                client.request("POST", "$endpoint/$action", JSONObject().put("actor", "android-user")) { result ->
                    result.onSuccess { reload() }.onFailure { showError(it) }
                }
            }.setNegativeButton("取消", null).show()
    }

    private fun resolveWarnings(decision: String) {
        if (selectedWarnings.isEmpty()) { showError(IllegalArgumentException("请先选择警告项")); return }
        val ids = JSONArray().apply { selectedWarnings.forEach { relationshipId -> put(relationshipId) } }
        val body = JSONObject().put("actor", "android-user").put("decision", decision).put("relationship_ids", ids)
        client.request("POST", "/api/v1/review/refunds/warnings/batch", body) { result ->
            result.onSuccess { reload() }.onFailure { showError(it) }
        }
    }

    private fun endpoint(type: String, item: JSONObject): String = when (type) {
        "imports" -> "/api/v1/import-reviews/${item.getString("session_id")}/items/${item.getString("review_item_id")}"
        "matches" -> "/api/v1/review/candidates/${item.getString("candidate_id")}"
        "refunds", "warnings", "acknowledged" -> "/api/v1/review/refunds/${item.getString("relationship_id")}"
        else -> "/api/v1/review/classifications/${item.getString("candidate_id")}"
    }

    private fun title(type: String, item: JSONObject): String {
        val source = when (type) { "imports" -> item.optJSONObject("raw"); "matches" -> item.optJSONObject("payment"); "refunds", "warnings", "acknowledged" -> item.optJSONObject("refund"); else -> item.optJSONObject("transaction") }
        return source?.optString("merchant")?.takeIf { it.isNotBlank() } ?: source?.optString("counterparty")?.takeIf { it.isNotBlank() } ?: "未命名交易"
    }

    private fun subtitle(type: String, item: JSONObject) = when (type) {
        "imports" -> item.optString("item_type", "导入变化")
        "matches", "refunds" -> "必须审核 · 置信度 ${item.optString("confidence", "-")}"
        "warnings" -> "Warning · 已自动归属 · ${if (item.optBoolean("is_ambiguous")) "多候选" else "部分退款"}"
        "acknowledged" -> "Warning · 已通过 · 可恢复"
        else -> "建议 ${item.optString("proposed_type", "-")} / ${item.optString("proposed_category", "未分类")}"
    }

    private fun showError(error: Throwable) { list.removeAllViews(); list.addView(message(error.message ?: "审核加载失败")) }
    private fun edit(hintText: String, value: String?) = EditText(context).apply { hint = hintText; setText(value.orEmpty()); minHeight = dp(52) }
    private fun message(value: String) = TextView(context).apply { text = value; gravity = Gravity.CENTER; setPadding(0, dp(32), 0, dp(32)) }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
