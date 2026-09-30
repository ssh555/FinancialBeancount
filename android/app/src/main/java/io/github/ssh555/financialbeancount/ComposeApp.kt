package io.github.ssh555.financialbeancount

import android.view.ViewGroup
import android.widget.ScrollView
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Assessment
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.ReceiptLong
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import java.math.BigDecimal
import java.net.URLEncoder
import java.text.NumberFormat
import java.time.LocalDate
import java.time.temporal.TemporalAdjusters
import java.util.Locale

private enum class LedgerDestination(val label: String, val icon: ImageVector) {
    Overview("概览", Icons.Outlined.Assessment),
    Transactions("交易", Icons.Outlined.ReceiptLong),
    Review("审核", Icons.Outlined.CheckCircle),
    Data("数据", Icons.Outlined.Storage),
}

@Composable
fun FinancialBeancountApp(client: NativeLedgerClient, dataView: NativeDataView) {
    var destination by remember { mutableStateOf(LedgerDestination.Overview) }
    Scaffold(
        containerColor = LedgerColors.Paper,
        bottomBar = {
            NavigationBar(containerColor = LedgerColors.Card) {
                LedgerDestination.entries.forEach { item ->
                    NavigationBarItem(
                        selected = destination == item,
                        onClick = { destination = item },
                        icon = { Icon(item.icon, contentDescription = null) },
                        label = { Text(item.label) },
                    )
                }
            }
        },
    ) { padding ->
        when (destination) {
            LedgerDestination.Overview -> ComposeOverview(client, Modifier.padding(padding))
            LedgerDestination.Transactions -> ComposeTransactions(client, Modifier.padding(padding))
            LedgerDestination.Review -> ComposeReview(client, Modifier.padding(padding))
            LedgerDestination.Data -> LegacySurface(Modifier.padding(padding)) { dataView }
        }
    }
}

@Composable
private fun LegacySurface(modifier: Modifier, content: (android.content.Context) -> android.view.View) {
    AndroidView(
        modifier = modifier.fillMaxSize(),
        factory = { context ->
            ScrollView(context).apply {
                isFillViewport = true
                addView(content(context), ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            }
        },
    )
}

private data class SummaryState(
    val knownBalance: String = "0",
    val balanceDate: String = "暂无日期",
    val netCashFlow: String = "0",
    val transactionNetCashFlow: String = "0",
    val netCashFlowBasis: String = "classified_transactions",
    val reconciliationAdjustment: String = "0",
    val expense: String = "0",
    val income: String = "0",
    val refunds: String = "0",
    val pendingReviewExcluded: Int = 0,
    val unclassifiedExcluded: Int = 0,
    val pendingBankAdjustment: String = "0",
)

private data class TimelineState(val period: String, val income: String, val expense: String, val net: String)

@Composable
private fun ComposeOverview(client: NativeLedgerClient, modifier: Modifier = Modifier) {
    var range by remember { mutableStateOf("all") }
    var grouping by remember { mutableStateOf("month") }
    var summary by remember { mutableStateOf(SummaryState()) }
    var timeline by remember { mutableStateOf(emptyList<TimelineState>()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(range, grouping) {
        loading = true
        error = null
        client.request("GET", "/api/v1/statistics/account-balances") { result ->
            result.onSuccess { response ->
                val data = response.getJSONObject("body").getJSONObject("data")
                val cashAccounts = data.optJSONArray("cash_accounts")
                summary = summary.copy(
                    knownBalance = data.optString("known_balance", "0"),
                    balanceDate = data.optString("as_of").takeUnless { it.isBlank() || it == "null" } ?: "暂无日期",
                    pendingBankAdjustment = if (cashAccounts == null) "0" else
                        (0 until cashAccounts.length()).fold(BigDecimal.ZERO) { total, index ->
                            total + (cashAccounts.getJSONObject(index).optString("pending_adjustment", "0").toBigDecimalOrNull() ?: BigDecimal.ZERO)
                        }.toPlainString(),
                )
            }.onFailure { error = it.message ?: "账户余额加载失败" }
        }
        val query = rangeQuery(range)
        client.request("GET", "/api/v1/statistics/summary?$query") { result ->
            result.onSuccess { response ->
                val data = response.getJSONObject("body").getJSONObject("data")
                summary = summary.copy(
                    netCashFlow = data.optString("net_cash_flow", "0"),
                    transactionNetCashFlow = data.optString("transaction_net_cash_flow", "0"),
                    netCashFlowBasis = data.optString("net_cash_flow_basis", "classified_transactions"),
                    reconciliationAdjustment = data.optString("asset_reconciliation_adjustment", "0"),
                    expense = data.optString("gross_expense", "0"),
                    income = data.optString("ordinary_income", "0"),
                    refunds = data.optString("refunds", "0"),
                    pendingReviewExcluded = data.optInt("pending_review_excluded_count"),
                    unclassifiedExcluded = data.optInt("unclassified_excluded_count"),
                )
            }.onFailure { error = it.message ?: "统计加载失败" }
        }
        client.request("GET", "/api/v1/statistics/timeline?period=$grouping&$query") { result ->
            loading = false
            result.onSuccess { response ->
                val rows = response.getJSONObject("body").getJSONArray("data")
                timeline = (0 until rows.length()).map { index ->
                    val item = rows.getJSONObject(index)
                    TimelineState(
                        "${item.optString("date_from")} ～ ${item.optString("date_to")}",
                        item.optString("ordinary_income", "0"),
                        item.optString("gross_expense", "0"),
                        item.optString("net_cash_flow", "0"),
                    )
                }
            }.onFailure { error = it.message ?: "周期统计加载失败" }
        }
    }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { Text("财务概览", style = androidx.compose.material3.MaterialTheme.typography.headlineLarge) }
        item { PeriodChips(listOf("今日" to "day", "本周" to "week", "本月" to "month", "本年" to "year", "全部" to "all"), range) { range = it } }
        item { BalanceCard(summary) }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                MetricRow(if (summary.netCashFlowBasis == "verified_asset_chain") "结余（资产链）" else "收支差额", summary.netCashFlow, "支出", summary.expense)
                MetricRow("收入", summary.income, "退款", summary.refunds)
                if (summary.netCashFlowBasis == "verified_asset_chain") {
                    Text("交易口径差额 ${money(summary.transactionNetCashFlow)} · 内部转移/理财等资产链调整 ${money(summary.reconciliationAdjustment)}", color = LedgerColors.Muted)
                }
                Text(
                    balanceExplanation(
                        range,
                        summary.knownBalance,
                        summary.netCashFlow,
                        summary.pendingReviewExcluded,
                        summary.unclassifiedExcluded,
                    ),
                    color = LedgerColors.Muted,
                )
            }
        }
        item { Text("周期收支", style = androidx.compose.material3.MaterialTheme.typography.titleLarge) }
        item { PeriodChips(listOf("日" to "day", "周" to "week", "月" to "month", "年" to "year"), grouping) { grouping = it } }
        if (loading) item { Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) { CircularProgressIndicator() } }
        error?.let { message -> item { Text(message, color = androidx.compose.material3.MaterialTheme.colorScheme.error) } }
        if (!loading && timeline.isEmpty()) item { Text("当前范围没有可统计交易", color = LedgerColors.Muted) }
        items(timeline) { item -> TimelineCard(item) }
    }
}

private fun balanceExplanation(
    range: String,
    knownBalance: String,
    netCashFlow: String,
    pendingReviewExcluded: Int,
    unclassifiedExcluded: Int,
): String {
    val known = knownBalance.toBigDecimalOrNull() ?: BigDecimal.ZERO
    val net = netCashFlow.toBigDecimalOrNull() ?: BigDecimal.ZERO
    val base = when {
        range != "all" -> "当前周期的收支差额不与账户余额直接比较；切换到全部账单查看校验"
        known.compareTo(net) == 0 -> "全部账单资产链结余与账户余额一致"
        known > net -> "账户余额比收支差额多 ${money((known - net).toPlainString())}：账单开始前可能有这部分余额未计入，或账单不完整"
        else -> "收支差额比账户余额多 ${money((net - known).toPlainString())}：可能有未记录支出，或账单不完整"
    }
    val details = buildList {
        if (pendingReviewExcluded > 0) add("$pendingReviewExcluded 笔待人工审核交易未计入")
        if (unclassifiedExcluded > 0) add("$unclassifiedExcluded 笔已确认但未分类交易未计入")
    }
    return if (details.isEmpty()) base else "$base · ${details.joinToString(" · ")}"
}

@Composable
private fun PeriodChips(options: List<Pair<String, String>>, selected: String, onSelect: (String) -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        options.forEach { (label, value) ->
            FilterChip(selected = selected == value, onClick = { onSelect(value) }, label = { Text(label) }, modifier = Modifier.weight(1f))
        }
    }
}

@Composable
private fun BalanceCard(state: SummaryState) {
    Card(colors = CardDefaults.cardColors(containerColor = LedgerColors.Primary), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(20.dp)) {
            Text("账户余额", color = androidx.compose.ui.graphics.Color.White)
            Text(money(state.knownBalance), color = androidx.compose.ui.graphics.Color.White, fontSize = 30.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(6.dp))
            val estimate = state.pendingBankAdjustment.toBigDecimalOrNull()?.takeIf { it.compareTo(BigDecimal.ZERO) != 0 }
                ?.let { " · 含待银行入账估算 ${money(it.toPlainString())}" }.orEmpty()
            Text("截至 ${state.balanceDate}$estimate · 不随来源筛选", color = androidx.compose.ui.graphics.Color.White.copy(alpha = 0.82f))
        }
    }
}

@Composable
private fun MetricRow(leftLabel: String, leftValue: String, rightLabel: String, rightValue: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        MetricCard(leftLabel, leftValue, Modifier.weight(1f))
        MetricCard(rightLabel, rightValue, Modifier.weight(1f))
    }
}

@Composable
private fun MetricCard(label: String, value: String, modifier: Modifier = Modifier) {
    Card(modifier = modifier, colors = CardDefaults.cardColors(containerColor = LedgerColors.Card)) {
        Column(Modifier.padding(16.dp)) {
            Text(label, color = LedgerColors.Muted)
            Spacer(Modifier.height(12.dp))
            Text(money(value), fontSize = 20.sp, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun TimelineCard(item: TimelineState) {
    Card(colors = CardDefaults.cardColors(containerColor = LedgerColors.Card), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text(item.period, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(8.dp))
            Text("收入 ${money(item.income)} · 支出 ${money(item.expense)}")
            Text("收支差额 ${money(item.net)}", color = LedgerColors.Muted)
        }
    }
}

private fun rangeQuery(range: String): String {
    val today = LocalDate.now()
    val start = when (range) {
        "day" -> today
        "week" -> today.minusDays((today.dayOfWeek.value - 1).toLong())
        "month" -> today.withDayOfMonth(1)
        "year" -> today.with(TemporalAdjusters.firstDayOfYear())
        else -> null
    }
    return if (start == null) "" else "date_from=${URLEncoder.encode(start.toString(), "UTF-8")}&date_to=$today"
}

private fun money(value: String): String = runCatching {
    NumberFormat.getCurrencyInstance(Locale.CHINA).format(value.toBigDecimal())
}.getOrElse { "¥0.00" }
