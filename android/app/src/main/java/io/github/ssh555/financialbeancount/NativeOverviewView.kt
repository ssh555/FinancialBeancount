package io.github.ssh555.financialbeancount

import android.content.Context
import android.graphics.Typeface
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import java.math.BigDecimal
import java.text.NumberFormat
import java.time.LocalDate
import java.time.temporal.TemporalAdjusters
import java.util.Locale

class NativeOverviewView(
    context: Context,
    private val client: NativeLedgerClient,
) : LinearLayout(context) {
    private val summary = LinearLayout(context)
    private val accountBalance = TextView(context)
    private val timeline = LinearLayout(context)
    private val progress = ProgressBar(context)
    private var range = "all"
    private var grouping = "month"
    private var knownBalanceValue: BigDecimal? = null
    private var netCashFlowValue: BigDecimal? = null
    private var excludedCount = 0
    private val reconciliationNote = TextView(context).apply {
        setTextColor(NativeUi.muted)
        setPadding(dp(4), dp(6), dp(4), dp(8))
    }
    private val sourceFilter = SourceFilterButton(context, client) { refresh() }

    init {
        orientation = VERTICAL
        setBackgroundColor(NativeUi.paper)
        setPadding(dp(16), dp(16), dp(16), dp(24))
        addView(title("财务概览", 26f))
        addView(sourceFilter)
        addView(periodChooser(listOf("今日" to "day", "本周" to "week", "本月" to "month", "本年" to "year", "全部" to "all"), range) { selected ->
            range = selected
            refresh()
        })
        accountBalance.setPadding(0, dp(16), 0, dp(8))
        accountBalance.textSize = 19f
        accountBalance.setTypeface(accountBalance.typeface, Typeface.BOLD)
        accountBalance.setTextColor(android.graphics.Color.WHITE)
        accountBalance.tag = "featured"
        accountBalance.setPadding(dp(16), dp(16), dp(16), dp(16))
        accountBalance.background = NativeUi.rounded(context, NativeUi.green, 18, NativeUi.green)
        addView(accountBalance)
        summary.orientation = VERTICAL
        summary.setPadding(0, dp(8), 0, dp(8))
        addView(summary)
        addView(title("周期收支", 18f))
        addView(periodChooser(listOf("日" to "day", "周" to "week", "月" to "month", "年" to "year"), grouping) { selected ->
            grouping = selected
            refresh()
        })
        timeline.orientation = VERTICAL
        addView(timeline)
        progress.visibility = View.GONE
        addView(progress, LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT).apply { gravity = Gravity.CENTER_HORIZONTAL })
        refresh()
    }

    fun refresh() {
        progress.visibility = View.VISIBLE
        val query = listOf(rangeQuery(), sourceFilter.query()).filter(String::isNotBlank).joinToString("&")
        client.request("GET", "/api/v1/statistics/account-balances") { result ->
            result.onSuccess { response ->
                val data = response.getJSONObject("body").getJSONObject("data")
                val asOf = data.optString("as_of")
                    .takeUnless { it.isBlank() || it == "null" }
                    ?: "暂无日期"
                accountBalance.text = "账户余额 ${money(data.getString("known_balance"))}\n截至 $asOf · 不随来源筛选"
                knownBalanceValue = data.getString("known_balance").toBigDecimal()
                updateReconciliationNote()
                NativeUi.styleTree(accountBalance)
            }.onFailure { accountBalance.text = it.message ?: "账户余额加载失败" }
        }
        client.request("GET", "/api/v1/statistics/summary?$query") { result ->
            result.onSuccess { response ->
                val data = response.getJSONObject("body").getJSONObject("data")
                excludedCount = data.optInt("pending_review_excluded_count") + data.optInt("unclassified_excluded_count")
                netCashFlowValue = data.getString("net_cash_flow").toBigDecimal()
                summary.removeAllViews()
                summary.addView(metricRow("收支差额", data.getString("net_cash_flow"), "支出", data.getString("gross_expense")))
                summary.addView(metricRow("收入", data.getString("ordinary_income"), "退款", data.getString("refunds")))
                summary.addView(reconciliationNote)
                updateReconciliationNote()
                NativeUi.styleTree(summary)
            }.onFailure {
                summary.removeAllViews()
                summary.addView(TextView(context).apply { text = it.message ?: "统计加载失败" })
            }
        }
        client.request("GET", "/api/v1/statistics/timeline?period=$grouping&$query") { result ->
            progress.visibility = View.GONE
            timeline.removeAllViews()
            result.onSuccess { response ->
                val rows = response.getJSONObject("body").getJSONArray("data")
                for (index in 0 until rows.length()) {
                    val item = rows.getJSONObject(index)
                    timeline.addView(TextView(context).apply {
                        textSize = 15f
                        setPadding(dp(14), dp(12), dp(14), dp(12))
                        text = "${item.getString("date_from")} ～ ${item.getString("date_to")}\n收入 ${money(item.getString("ordinary_income"))}   支出 ${money(item.getString("gross_expense"))}   收支差额 ${money(item.getString("net_cash_flow"))}"
                        NativeUi.card(this, 14)
                    })
                }
                if (rows.length() == 0) timeline.addView(TextView(context).apply { text = "当前范围没有可统计交易" })
                NativeUi.styleTree(timeline)
            }.onFailure { timeline.addView(TextView(context).apply { text = it.message ?: "周期统计加载失败" }) }
        }
    }

    private fun updateReconciliationNote() {
        val known = knownBalanceValue
        val net = netCashFlowValue
        val base = when {
            range != "all" || sourceFilter.query().isNotBlank() -> "当前筛选的收支差额不与账户余额直接比较；切换到全部账单与全部来源查看校验"
            known == null || net == null -> "正在校验全部账单与账户余额…"
            known.compareTo(net) == 0 -> "全部账单收支差额与账户余额一致"
            known > net -> "账户余额比收支差额多 ${money((known - net).toPlainString())}：账单开始前可能有这部分余额未计入，或账单不完整"
            else -> "收支差额比账户余额多 ${money((net - known).toPlainString())}：可能有未记录支出，或账单不完整"
        }
        reconciliationNote.text = if (excludedCount > 0) "$base · $excludedCount 笔待处理交易未计入" else base
    }

    private fun periodChooser(items: List<Pair<String, String>>, selectedValue: String, select: (String) -> Unit): View =
        LinearLayout(context).apply {
            orientation = HORIZONTAL
            setPadding(dp(4), dp(4), dp(4), dp(4))
            background = NativeUi.rounded(context, android.graphics.Color.rgb(229, 230, 224), 12, android.graphics.Color.rgb(229, 230, 224))
            val buttons = mutableListOf<Pair<Button, String>>()
            items.forEach { (label, value) ->
                val button = Button(context).apply {
                    text = label
                    minWidth = 0
                    minHeight = dp(48)
                    tag = if (value == selectedValue) "primary" else null
                    NativeUi.styleButton(this, primary = value == selectedValue)
                    setOnClickListener {
                        buttons.forEach { (candidate, candidateValue) ->
                            candidate.tag = if (candidateValue == value) "primary" else null
                            NativeUi.styleButton(candidate, primary = candidateValue == value)
                        }
                        select(value)
                    }
                }
                buttons += button to value
                addView(button, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
            }
        }

    private fun rangeQuery(): String {
        val today = LocalDate.now()
        val start = when (range) {
            "day" -> today
            "week" -> today.minusDays((today.dayOfWeek.value - 1).toLong())
            "month" -> today.withDayOfMonth(1)
            "year" -> today.with(TemporalAdjusters.firstDayOfYear())
            else -> null
        }
        return if (start == null) "" else "date_from=$start&date_to=$today"
    }

    private fun metricRow(leftLabel: String, leftValue: String, rightLabel: String, rightValue: String) =
        LinearLayout(context).apply {
            orientation = HORIZONTAL
            addView(metric(leftLabel, leftValue), LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f).apply { setMargins(0, dp(5), dp(5), dp(5)) })
            addView(metric(rightLabel, rightValue), LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f).apply { setMargins(dp(5), dp(5), 0, dp(5)) })
        }

    private fun metric(label: String, value: String) = LinearLayout(context).apply {
        orientation = VERTICAL
        minimumHeight = dp(112)
        setPadding(dp(14), dp(14), dp(14), dp(12))
        NativeUi.card(this)
        addView(TextView(context).apply { text = label; setTextColor(NativeUi.muted); textSize = 13f })
        addView(TextView(context).apply { text = money(value); textSize = 20f; setTypeface(typeface, Typeface.BOLD); setPadding(0, dp(12), 0, 0) })
    }

    private fun money(value: String): String = NumberFormat.getCurrencyInstance(Locale.CHINA).format(value.toBigDecimal())
    private fun title(value: String, size: Float) = TextView(context).apply { text = value; textSize = size; setTypeface(typeface, Typeface.BOLD); setPadding(0, dp(8), 0, dp(10)) }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
