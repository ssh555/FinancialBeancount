package io.github.ssh555.financialbeancount

import android.content.Context
import android.graphics.Typeface
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import java.text.NumberFormat
import java.time.LocalDate
import java.time.temporal.TemporalAdjusters
import java.util.Locale

class NativeOverviewView(
    context: Context,
    private val client: NativeLedgerClient,
) : LinearLayout(context) {
    private val summary = TextView(context)
    private val accountBalance = TextView(context)
    private val timeline = LinearLayout(context)
    private val progress = ProgressBar(context)
    private var range = "all"
    private var grouping = "month"
    private val sourceFilter = SourceFilterButton(context, client) { refresh() }

    init {
        orientation = VERTICAL
        setPadding(dp(16), dp(16), dp(16), dp(24))
        addView(title("财务概览", 26f))
        addView(sourceFilter)
        addView(periodChooser(listOf("今日" to "day", "本周" to "week", "本月" to "month", "本年" to "year", "全部" to "all")) { selected ->
            range = selected
            refresh()
        })
        accountBalance.setPadding(0, dp(16), 0, dp(8))
        accountBalance.textSize = 19f
        accountBalance.setTypeface(accountBalance.typeface, Typeface.BOLD)
        addView(accountBalance)
        summary.setPadding(0, dp(16), 0, dp(16))
        summary.textSize = 17f
        addView(summary)
        addView(title("周期收支", 18f))
        addView(periodChooser(listOf("日" to "day", "周" to "week", "月" to "month", "年" to "year")) { selected ->
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
                accountBalance.text = "账户余额 ${money(data.getString("known_balance"))}\n截至 ${data.optString("as_of", "暂无日期")} · 不随来源筛选"
            }.onFailure { accountBalance.text = it.message ?: "账户余额加载失败" }
        }
        client.request("GET", "/api/v1/statistics/summary?$query") { result ->
            result.onSuccess { response ->
                val data = response.getJSONObject("body").getJSONObject("data")
                val excluded = data.optInt("pending_review_excluded_count") + data.optInt("unclassified_excluded_count")
                val note = if (excluded > 0) "\n$excluded 笔待审核或未分类交易未计入收支" else ""
                summary.text = "收支差额 ${money(data.getString("net_cash_flow"))}   支出 ${money(data.getString("gross_expense"))}\n收入 ${money(data.getString("ordinary_income"))}   退款 ${money(data.getString("refunds"))}\n收支差额不是账户当前余额$note"
            }.onFailure { summary.text = it.message ?: "统计加载失败" }
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
                        setPadding(0, dp(12), 0, dp(12))
                        text = "${item.getString("date_from")} ～ ${item.getString("date_to")}\n收入 ${money(item.getString("ordinary_income"))}   支出 ${money(item.getString("gross_expense"))}   收支差额 ${money(item.getString("net_cash_flow"))}"
                    })
                }
                if (rows.length() == 0) timeline.addView(TextView(context).apply { text = "当前范围没有可统计交易" })
            }.onFailure { timeline.addView(TextView(context).apply { text = it.message ?: "周期统计加载失败" }) }
        }
    }

    private fun periodChooser(items: List<Pair<String, String>>, select: (String) -> Unit): View =
        HorizontalScrollView(context).apply {
            isHorizontalScrollBarEnabled = false
            addView(LinearLayout(context).apply {
                orientation = HORIZONTAL
                items.forEach { (label, value) ->
                    addView(Button(context).apply {
                        text = label
                        minHeight = dp(48)
                        setOnClickListener { select(value) }
                    })
                }
            })
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

    private fun money(value: String): String = NumberFormat.getCurrencyInstance(Locale.CHINA).format(value.toBigDecimal())
    private fun title(value: String, size: Float) = TextView(context).apply { text = value; textSize = size; setTypeface(typeface, Typeface.BOLD); setPadding(0, dp(8), 0, dp(10)) }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
