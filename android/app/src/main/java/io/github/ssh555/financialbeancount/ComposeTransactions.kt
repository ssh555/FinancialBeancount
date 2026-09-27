package io.github.ssh555.financialbeancount

import androidx.compose.foundation.clickable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.RestoreFromTrash
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject
import java.net.URLEncoder
import java.text.NumberFormat
import java.time.LocalDate
import java.util.Locale

private data class TransactionRow(
    val id: String,
    val date: String,
    val amount: String,
    val merchant: String,
    val category: String,
    val direction: String,
    val notes: String = "",
)

private data class SourceOption(val label: String, val value: String)

@Composable
fun ComposeTransactions(client: NativeLedgerClient, modifier: Modifier = Modifier) {
    var queryDraft by remember { mutableStateOf("") }
    var query by remember { mutableStateOf("") }
    var selectedSources by remember { mutableStateOf(emptySet<String>()) }
    var sourceOptions by remember { mutableStateOf(emptyList<SourceOption>()) }
    var showSources by remember { mutableStateOf(false) }
    var rows by remember { mutableStateOf(emptyList<TransactionRow>()) }
    var page by remember { mutableIntStateOf(1) }
    var total by remember { mutableIntStateOf(0) }
    var reloadToken by remember { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var detail by remember { mutableStateOf<TransactionRow?>(null) }
    var editing by remember { mutableStateOf<TransactionRow?>(null) }
    var creating by remember { mutableStateOf(false) }
    var deleteTarget by remember { mutableStateOf<TransactionRow?>(null) }
    var trash by remember { mutableStateOf<List<TransactionRow>?>(null) }

    fun reload() { page = 1; reloadToken += 1 }
    fun mutate(method: String, target: String, body: JSONObject) {
        loading = true
        client.request(method, target, body) { result ->
            loading = false
            result.onSuccess { detail = null; editing = null; creating = false; deleteTarget = null; trash = null; reload() }
                .onFailure { error = it.message ?: "操作失败" }
        }
    }

    LaunchedEffect(page, query, selectedSources, reloadToken) {
        loading = true
        error = null
        val sourceQuery = selectedSources.joinToString("&") { "source=${URLEncoder.encode(it, "UTF-8")}" }
        val suffix = if (sourceQuery.isBlank()) "" else "&$sourceQuery"
        client.request("GET", "/api/v1/transactions?page=$page&page_size=30&search=${URLEncoder.encode(query, "UTF-8")}$suffix") { result ->
            loading = false
            result.onSuccess { response ->
                val body = response.getJSONObject("body")
                val data = body.getJSONArray("data")
                val loaded = (0 until data.length()).map { index -> data.getJSONObject(index).toTransaction() }
                rows = if (page == 1) loaded else rows + loaded
                total = body.getJSONObject("meta").optInt("total")
            }.onFailure { error = it.message ?: "交易加载失败" }
        }
    }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("交易", style = androidx.compose.material3.MaterialTheme.typography.headlineLarge, modifier = Modifier.weight(1f))
                IconButton(onClick = { creating = true }) { Icon(Icons.Outlined.Add, contentDescription = "记一笔") }
                IconButton(onClick = {
                    client.request("GET", "/api/v1/deleted-transactions?page=1&page_size=200") { result ->
                        result.onSuccess { response ->
                            val data = response.getJSONObject("body").getJSONArray("data")
                            trash = (0 until data.length()).map { data.getJSONObject(it).toTransaction() }
                        }.onFailure { error = it.message ?: "回收站加载失败" }
                    }
                }) { Icon(Icons.Outlined.RestoreFromTrash, contentDescription = "回收站") }
            }
        }
        item {
            OutlinedTextField(
                value = queryDraft,
                onValueChange = { queryDraft = it },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                label = { Text("搜索商户或备注") },
                trailingIcon = { IconButton(onClick = { query = queryDraft.trim(); reload() }) { Icon(Icons.Outlined.Search, contentDescription = "搜索") } },
            )
        }
        item {
            OutlinedButton(onClick = {
                client.request("GET", "/api/v1/sources") { result ->
                    result.onSuccess { response ->
                        val data = response.getJSONObject("body").getJSONArray("data")
                        val platforms = mutableSetOf<String>()
                        val options = mutableListOf<SourceOption>()
                        val names = mapOf("alipay" to "支付宝", "wechat" to "微信", "bank" to "银行", "unionpay" to "云闪付")
                        for (index in 0 until data.length()) {
                            val item = data.getJSONObject(index)
                            val source = item.getString("source")
                            if (platforms.add(source)) options += SourceOption("${names[source] ?: source}（全部账户）", source)
                            options += SourceOption("${item.getString("source_account")} · ${item.optInt("transaction_count")} 笔", "$source::${item.getString("source_account")}")
                        }
                        sourceOptions = options
                        showSources = true
                    }.onFailure { error = it.message ?: "来源加载失败" }
                }
            }) { Text(if (selectedSources.isEmpty()) "来源：全部" else "来源：已选 ${selectedSources.size} 项") }
        }
        if (loading && rows.isEmpty()) item { Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) { CircularProgressIndicator() } }
        error?.let { message -> item { Text(message, color = androidx.compose.material3.MaterialTheme.colorScheme.error) } }
        if (!loading && rows.isEmpty() && error == null) item { EmptyTransactions { creating = true } }
        items(rows, key = { it.id }) { item -> TransactionCard(item) { detail = item } }
        if (rows.size < total) item { OutlinedButton(onClick = { page += 1 }, enabled = !loading, modifier = Modifier.fillMaxWidth()) { Text(if (loading) "加载中…" else "加载更多") } }
    }

    if (showSources) SourceDialog(sourceOptions, selectedSources, { showSources = false }) { selectedSources = it; showSources = false; reload() }
    detail?.let { item -> TransactionDetail(item, { detail = null }, { editing = item; detail = null }, { deleteTarget = item; detail = null }) }
    if (creating) TransactionEditor(null, { creating = false }) { body -> mutate("POST", "/api/v1/transactions", body.put("actor", "android-user")) }
    editing?.let { item -> TransactionEditor(item, { editing = null }) { changes -> mutate("PATCH", "/api/v1/transactions/${item.id}", JSONObject().put("actor", "android-user").put("changes", changes)) } }
    deleteTarget?.let { item -> ConfirmDelete(item, { deleteTarget = null }) { mutate("DELETE", "/api/v1/transactions/${item.id}", JSONObject().put("actor", "android-user").put("reason", "user_deleted")) } }
    trash?.let { items -> TrashDialog(items, { trash = null }) { item -> mutate("POST", "/api/v1/transactions/${item.id}/restore", JSONObject().put("actor", "android-user")) } }
}

@Composable
private fun TransactionCard(item: TransactionRow, open: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = open),
        colors = CardDefaults.cardColors(containerColor = LedgerColors.Card),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(Modifier.fillMaxWidth()) {
                Text(item.merchant.ifBlank { "未命名交易" }, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                Text(moneyText(item.amount), fontWeight = FontWeight.Bold, color = if (item.direction == "income") LedgerColors.Primary else LedgerColors.Ink)
            }
            Text("${item.date} · ${item.category.ifBlank { "未分类" }}", color = LedgerColors.Muted, modifier = Modifier.padding(top = 6.dp))
        }
    }
}

@Composable
private fun EmptyTransactions(create: () -> Unit) {
    Card(colors = CardDefaults.cardColors(containerColor = LedgerColors.Card), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text("没有符合条件的交易", fontWeight = FontWeight.SemiBold)
            Text("可以调整筛选条件，或手动记录一笔。", color = LedgerColors.Muted, modifier = Modifier.padding(vertical = 8.dp))
            Button(onClick = create) { Icon(Icons.Outlined.Add, null); Text("记一笔") }
        }
    }
}

@Composable
private fun SourceDialog(options: List<SourceOption>, selected: Set<String>, dismiss: () -> Unit, apply: (Set<String>) -> Unit) {
    var draft by remember(selected) { mutableStateOf(selected) }
    AlertDialog(
        onDismissRequest = dismiss,
        title = { Text("选择来源") },
        text = { LazyColumn(Modifier.heightIn(max = 420.dp)) { items(options) { item -> Row(Modifier.fillMaxWidth().clickable { draft = if (item.value in draft) draft - item.value else draft + item.value }, verticalAlignment = Alignment.CenterVertically) { Checkbox(item.value in draft, { checked -> draft = if (checked) draft + item.value else draft - item.value }); Text(item.label) } } } },
        confirmButton = { TextButton(onClick = { apply(draft) }) { Text("应用") } },
        dismissButton = { Row { TextButton(onClick = { apply(emptySet()) }) { Text("清除") }; TextButton(onClick = dismiss) { Text("取消") } } },
    )
}

@Composable
private fun TransactionDetail(item: TransactionRow, dismiss: () -> Unit, edit: () -> Unit, delete: () -> Unit) {
    AlertDialog(
        onDismissRequest = dismiss,
        title = { Text(item.merchant.ifBlank { "交易详情" }) },
        text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) { Text(moneyText(item.amount), fontSize = 26.sp, fontWeight = FontWeight.Bold); Text("日期：${item.date}"); Text("分类：${item.category.ifBlank { "未分类" }}"); Text("备注：${item.notes.ifBlank { "无" }}") } },
        confirmButton = { TextButton(onClick = edit) { Text("编辑") } },
        dismissButton = { Row { TextButton(onClick = delete) { Icon(Icons.Outlined.DeleteOutline, null); Text("删除") }; TextButton(onClick = dismiss) { Text("关闭") } } },
    )
}

@Composable
private fun TransactionEditor(item: TransactionRow?, dismiss: () -> Unit, save: (JSONObject) -> Unit) {
    var date by remember { mutableStateOf(item?.date.orEmpty()) }
    var amount by remember { mutableStateOf(item?.amount.orEmpty()) }
    var merchant by remember { mutableStateOf(item?.merchant.orEmpty()) }
    var category by remember { mutableStateOf(item?.category.orEmpty()) }
    var notes by remember { mutableStateOf(item?.notes.orEmpty()) }
    var direction by remember { mutableStateOf(item?.direction ?: "expense") }
    var attempted by remember { mutableStateOf(false) }
    val validDate = runCatching { LocalDate.parse(date.trim()) }.isSuccess
    val validAmount = amount.trim().toBigDecimalOrNull()?.signum()?.let { it != 0 } == true
    val validMerchant = merchant.isNotBlank()
    AlertDialog(
        onDismissRequest = dismiss,
        title = { Text(if (item == null) "新增交易" else "编辑交易") },
        text = {
            LazyColumn(Modifier.heightIn(max = 500.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                item { OutlinedTextField(date, { date = it }, label = { Text("交易日期") }, supportingText = { Text("YYYY-MM-DD") }, isError = attempted && !validDate, singleLine = true) }
                item { OutlinedTextField(amount, { amount = it }, label = { Text("金额") }, isError = attempted && !validAmount, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), singleLine = true) }
                item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { FilterChip(direction == "expense", { direction = "expense" }, { Text("支出") }); FilterChip(direction == "income", { direction = "income" }, { Text("收入") }) } }
                item { OutlinedTextField(merchant, { merchant = it }, label = { Text("商户或交易对象") }, isError = attempted && !validMerchant, singleLine = true) }
                item { OutlinedTextField(category, { category = it }, label = { Text("分类") }, singleLine = true) }
                item { OutlinedTextField(notes, { notes = it }, label = { Text("备注（可选）") }, minLines = 2) }
            }
        },
        confirmButton = { Button(onClick = { attempted = true; if (validDate && validAmount && validMerchant) save(JSONObject().put("booking_date", date.trim()).put("amount", amount.trim()).put("direction", direction).put("merchant", merchant.trim()).put("category", category.trim()).put("notes", notes.trim()).put("tx_type", direction)) }) { Text("保存") } },
        dismissButton = { TextButton(onClick = dismiss) { Text("取消") } },
    )
}

@Composable
private fun ConfirmDelete(item: TransactionRow, dismiss: () -> Unit, confirm: () -> Unit) {
    AlertDialog(onDismissRequest = dismiss, title = { Text("移入回收站？") }, text = { Text("“${item.merchant}”将从统计和导出中移除，原始来源和审计记录会保留。") }, confirmButton = { Button(onClick = confirm) { Text("移入回收站") } }, dismissButton = { TextButton(onClick = dismiss) { Text("取消") } })
}

@Composable
private fun TrashDialog(rows: List<TransactionRow>, dismiss: () -> Unit, restore: (TransactionRow) -> Unit) {
    AlertDialog(onDismissRequest = dismiss, title = { Text("回收站") }, text = { if (rows.isEmpty()) Text("回收站为空") else LazyColumn(Modifier.heightIn(max = 440.dp)) { items(rows, key = { it.id }) { item -> Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) { Column(Modifier.weight(1f)) { Text(item.merchant.ifBlank { "未命名交易" }, fontWeight = FontWeight.SemiBold); Text("${item.date} · ${moneyText(item.amount)}", color = LedgerColors.Muted) }; TextButton(onClick = { restore(item) }) { Text("恢复") } } } } }, confirmButton = { TextButton(onClick = dismiss) { Text("关闭") } })
}

private fun JSONObject.toTransaction() = TransactionRow(
    id = optString("canonical_id"),
    date = optString("booking_date"),
    amount = optString("amount", "0"),
    merchant = optString("merchant"),
    category = optString("category"),
    direction = optString("direction"),
    notes = optString("notes"),
)

private fun moneyText(value: String) = runCatching { NumberFormat.getCurrencyInstance(Locale.CHINA).format(value.toBigDecimal()) }.getOrElse { "¥0.00" }
