package io.github.ssh555.financialbeancount

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject

private data class ReviewQueue(val label: String, val value: String)

private val reviewQueues = listOf(
    ReviewQueue("导入", "imports"), ReviewQueue("归并", "matches"),
    ReviewQueue("退款", "refunds"), ReviewQueue("分类", "classifications"),
    ReviewQueue("警告", "warnings"), ReviewQueue("已通过", "acknowledged"),
)

@Composable
fun ComposeReview(client: NativeLedgerClient, modifier: Modifier = Modifier) {
    var type by remember { mutableStateOf("imports") }
    var rows by remember { mutableStateOf(emptyList<JSONObject>()) }
    var selected by remember { mutableStateOf(emptySet<String>()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var reloadToken by remember { mutableIntStateOf(0) }
    var detail by remember { mutableStateOf<JSONObject?>(null) }
    var moreActions by remember { mutableStateOf<JSONObject?>(null) }
    var editing by remember { mutableStateOf<JSONObject?>(null) }

    fun reload() { selected = emptySet(); detail = null; moreActions = null; editing = null; reloadToken += 1 }
    fun post(endpoint: String, action: String, body: JSONObject = JSONObject().put("actor", "android-user")) {
        loading = true
        client.request("POST", "$endpoint/$action", body) { result ->
            loading = false
            result.onSuccess { reload() }.onFailure { error = it.message ?: "审核操作失败" }
        }
    }
    fun resolveWarnings(decision: String) {
        if (selected.isEmpty()) { error = "请先选择警告项"; return }
        val ids = JSONArray().apply { selected.forEach { put(it) } }
        client.request("POST", "/api/v1/review/refunds/warnings/batch", JSONObject().put("actor", "android-user").put("decision", decision).put("relationship_ids", ids)) { result ->
            result.onSuccess { reload() }.onFailure { error = it.message ?: "批量操作失败" }
        }
    }

    LaunchedEffect(type, reloadToken) {
        loading = true; error = null; rows = emptyList(); selected = emptySet()
        if (type == "imports") {
            client.request("GET", "/api/v1/import-reviews?status=pending&page_size=100") { sessionsResult ->
                sessionsResult.onFailure { loading = false; error = it.message ?: "导入审核加载失败" }
                sessionsResult.onSuccess { response ->
                    val sessions = response.getJSONObject("body").getJSONArray("data")
                    if (sessions.length() == 0) { rows = emptyList(); loading = false }
                    else {
                        val combined = mutableListOf<JSONObject>()
                        var remaining = sessions.length()
                        for (index in 0 until sessions.length()) {
                            val sessionId = sessions.getJSONObject(index).getString("session_id")
                            client.request("GET", "/api/v1/import-reviews/$sessionId/items?page_size=200") { itemResult ->
                                itemResult.onSuccess { itemResponse ->
                                    val data = itemResponse.getJSONObject("body").getJSONArray("data")
                                    for (itemIndex in 0 until data.length()) {
                                        val item = data.getJSONObject(itemIndex)
                                        if (item.optString("status") == "pending") combined += JSONObject(item.toString()).put("session_id", sessionId)
                                    }
                                }.onFailure { error = it.message ?: "导入审核项加载失败" }
                                remaining -= 1
                                if (remaining == 0) { rows = combined; loading = false }
                            }
                        }
                    }
                }
            }
        } else {
            val route = mapOf("matches" to "candidates", "refunds" to "refunds", "classifications" to "classifications", "warnings" to "refunds", "acknowledged" to "refunds").getValue(type)
            val query = when (type) { "warnings" -> "attention=warning"; "acknowledged" -> "attention=acknowledged"; else -> "status=pending" }
            client.request("GET", "/api/v1/review/$route?$query&page_size=100") { result ->
                loading = false
                result.onSuccess { response ->
                    val data = response.getJSONObject("body").getJSONArray("data")
                    rows = (0 until data.length()).map(data::getJSONObject)
                }.onFailure { error = it.message ?: "审核列表加载失败" }
            }
        }
    }

    LazyColumn(modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { Text("待处理", style = androidx.compose.material3.MaterialTheme.typography.headlineLarge) }
        item { Text("先处理必须项；可确认、修正、关联、保留独立、排除或暂缓。", color = LedgerColors.Muted) }
        item {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(reviewQueues) { queue -> FilterChip(selected = type == queue.value, onClick = { type = queue.value }, label = { Text(queue.label) }) }
            }
        }
        if (type == "warnings" || type == "acknowledged") item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { selected = rows.mapNotNull { it.optString("relationship_id").takeIf(String::isNotBlank) }.toSet() }) { Text("全选") }
                if (type == "warnings") {
                    OutlinedButton(onClick = { resolveWarnings("escalate") }) { Text("不通过") }
                    Button(onClick = { resolveWarnings("acknowledge") }) { Text("批量通过") }
                } else Button(onClick = { resolveWarnings("restore") }) { Text("恢复 Warning") }
            }
        }
        if (loading) item { Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) { CircularProgressIndicator() } }
        error?.let { message -> item { Text(message, color = androidx.compose.material3.MaterialTheme.colorScheme.error) } }
        if (!loading && rows.isEmpty()) item { ReviewEmpty(reviewQueues.first { it.value == type }.label) }
        items(rows, key = { reviewEndpoint(type, it) }) { item ->
            val relationshipId = item.optString("relationship_id")
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (type == "warnings" || type == "acknowledged") Checkbox(relationshipId in selected, { checked -> selected = if (checked) selected + relationshipId else selected - relationshipId })
                ReviewCard(type, item, Modifier.weight(1f)) { detail = item }
            }
        }
    }

    detail?.let { item -> ReviewDetail(type, item, { detail = null }, {
        post(reviewEndpoint(type, item), "confirm")
    }, { moreActions = item; detail = null }) }
    moreActions?.let { item -> MoreReviewActions(type, { moreActions = null }, { editing = item; moreActions = null }, { post(reviewEndpoint(type, item), "reject") }) }
    editing?.let { item -> ReviewEdit(type, item, { editing = null }) { changes ->
        val endpoint = reviewEndpoint(type, item)
        val action = if (type == "imports") "modify" else "confirm"
        post(endpoint, action, JSONObject().put("actor", "android-user").put("changes", changes))
    } }
}

@Composable
private fun ReviewCard(type: String, item: JSONObject, modifier: Modifier, open: () -> Unit) {
    Card(modifier.clickable(onClick = open), colors = CardDefaults.cardColors(containerColor = LedgerColors.Card)) {
        Column(Modifier.fillMaxWidth().padding(16.dp)) {
            Text(reviewTitle(type, item), fontWeight = FontWeight.Bold)
            Text(reviewSubtitle(type, item), color = LedgerColors.Muted, modifier = Modifier.padding(top = 6.dp))
        }
    }
}

@Composable
private fun ReviewEmpty(label: String) {
    Card(colors = CardDefaults.cardColors(containerColor = LedgerColors.Card), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) { Text("${label}暂无待处理项", fontWeight = FontWeight.SemiBold); Text("可切换上方分类继续检查。", color = LedgerColors.Muted, modifier = Modifier.padding(top = 6.dp)) }
    }
}

@Composable
private fun ReviewDetail(type: String, item: JSONObject, dismiss: () -> Unit, confirm: () -> Unit, more: () -> Unit) {
    AlertDialog(
        onDismissRequest = dismiss,
        title = { Text(reviewTitle(type, item)) },
        text = { Column(verticalArrangement = Arrangement.spacedBy(7.dp)) { reviewSources(type, item).forEach { (label, source) -> Text(label, color = LedgerColors.Primary, fontWeight = FontWeight.Bold); Text("商户：${source.optString("merchant").ifBlank { source.optString("counterparty", "未命名") }}"); source.optString("amount").takeIf { it.isNotBlank() && it != "null" }?.let { Text("金额：$it") }; source.optString("booking_date").takeIf { it.isNotBlank() && it != "null" }?.let { Text("日期：$it") } }; Text(reviewSubtitle(type, item), color = LedgerColors.Muted) } },
        confirmButton = { if (type != "warnings" && type != "acknowledged") Button(onClick = confirm) { Text(if (type == "matches" || type == "refunds") "关联/合并" else "确认并入") } },
        dismissButton = { Row { if (type != "warnings" && type != "acknowledged") TextButton(onClick = more) { Text("更多处理") }; TextButton(onClick = dismiss) { Text("关闭") } } },
    )
}

@Composable
private fun MoreReviewActions(type: String, dismiss: () -> Unit, edit: () -> Unit, reject: () -> Unit) {
    val preserve = when (type) { "matches", "refunds" -> "保留为独立交易"; "classifications" -> "保留原分类"; else -> "排除此项" }
    AlertDialog(onDismissRequest = dismiss, title = { Text("选择处理方式") }, text = { Column { TextButton(onClick = edit, modifier = Modifier.fillMaxWidth()) { Text("修正信息") }; TextButton(onClick = reject, modifier = Modifier.fillMaxWidth()) { Text(preserve) }; TextButton(onClick = dismiss, modifier = Modifier.fillMaxWidth()) { Text("暂缓处理") } } }, confirmButton = {}, dismissButton = { TextButton(onClick = dismiss) { Text("取消") } })
}

@Composable
private fun ReviewEdit(type: String, item: JSONObject, dismiss: () -> Unit, save: (JSONObject) -> Unit) {
    val source = when (type) { "imports" -> item.optJSONObject("raw"); "matches" -> item.optJSONObject("payment"); "refunds" -> item.optJSONObject("refund"); else -> item.optJSONObject("transaction") }
    val initialMerchant = source?.let { it.optString("merchant").ifBlank { it.optString("counterparty") } }.orEmpty()
    var merchant by remember { mutableStateOf(initialMerchant) }
    var category by remember { mutableStateOf(source?.optString("category").orEmpty()) }
    var notes by remember { mutableStateOf(source?.optString("notes").orEmpty()) }
    AlertDialog(onDismissRequest = dismiss, title = { Text("修正信息") }, text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) { OutlinedTextField(merchant, { merchant = it }, label = { Text("商户") }); OutlinedTextField(category, { category = it }, label = { Text("分类") }); OutlinedTextField(notes, { notes = it }, label = { Text("备注") }, minLines = 2) } }, confirmButton = { Button(onClick = { save(JSONObject().put("merchant", merchant.trim()).put("category", category.trim()).put("notes", notes.trim())) }) { Text("保存并完成") } }, dismissButton = { TextButton(onClick = dismiss) { Text("取消") } })
}

private fun reviewEndpoint(type: String, item: JSONObject): String = when (type) {
    "imports" -> "/api/v1/import-reviews/${item.optString("session_id")}/items/${item.optString("review_item_id")}"
    "matches" -> "/api/v1/review/candidates/${item.optString("candidate_id")}"
    "refunds", "warnings", "acknowledged" -> "/api/v1/review/refunds/${item.optString("relationship_id")}"
    else -> "/api/v1/review/classifications/${item.optString("candidate_id")}"
}

private fun reviewSources(type: String, item: JSONObject): List<Pair<String, JSONObject>> = when (type) {
    "imports" -> listOfNotNull(item.optJSONObject("raw")?.let { "导入内容" to it })
    "matches" -> listOfNotNull(item.optJSONObject("payment")?.let { "付款记录" to it }, item.optJSONObject("candidate")?.let { "候选记录" to it })
    "refunds", "warnings", "acknowledged" -> listOfNotNull(item.optJSONObject("refund")?.let { "退款记录" to it }, item.optJSONObject("payment")?.let { "关联付款" to it })
    else -> listOfNotNull(item.optJSONObject("transaction")?.let { "交易记录" to it })
}

private fun reviewTitle(type: String, item: JSONObject): String = reviewSources(type, item).firstOrNull()?.second?.let { source -> source.optString("merchant").ifBlank { source.optString("counterparty", "未命名交易") } } ?: "未命名交易"

private fun reviewSubtitle(type: String, item: JSONObject): String = when (type) {
    "imports" -> item.optString("item_type", "导入变化")
    "matches", "refunds" -> "必须审核 · 置信度 ${item.optString("confidence", "-")}"
    "warnings" -> "Warning · 已自动归属 · ${if (item.optBoolean("is_ambiguous")) "多候选" else "部分退款"}"
    "acknowledged" -> "Warning · 已通过 · 可恢复"
    else -> "建议 ${item.optString("proposed_type", "-")} / ${item.optString("proposed_category", "未分类")}"
}
