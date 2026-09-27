package io.github.ssh555.financialbeancount

import android.content.Context
import android.graphics.Typeface
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView

class NativeAppView(
    context: Context,
    client: NativeLedgerClient,
    host: NativeDataView.Host,
) : LinearLayout(context) {
    val dataView = NativeDataView(context, client, host)

    private val content = FrameLayout(context)
    private val pageFactories = linkedMapOf<String, () -> View>(
        "概览" to { NativeOverviewView(context, client) },
        "交易" to { NativeTransactionsView(context, client) },
        "审核" to { NativeReviewView(context, client) },
        "数据" to { dataView },
    )
    private val pages = mutableMapOf<String, View>()
    private val pageContainers = mutableMapOf<String, ScrollView>()
    private val navigation = LinearLayout(context)

    init {
        orientation = VERTICAL
        setBackgroundColor(NativeUi.paper)
        content.addView(containerFor("概览"))
        addView(content, LayoutParams(LayoutParams.MATCH_PARENT, 0, 1f))

        navigation.orientation = HORIZONTAL
        navigation.gravity = Gravity.CENTER
        navigation.setPadding(dp(4), dp(4), dp(4), dp(4))
        navigation.setBackgroundColor(NativeUi.card)
        navigation.elevation = dp(10).toFloat()
        pageFactories.forEach { (label, _) ->
            navigation.addView(Button(context).apply {
                text = "${mapOf("概览" to "⌂", "交易" to "≡", "审核" to "✓", "数据" to "⇄").getValue(label)}\n$label"
                isAllCaps = false
                minHeight = dp(56)
                backgroundTintList = android.content.res.ColorStateList.valueOf(android.graphics.Color.TRANSPARENT)
                setTextColor(NativeUi.muted)
                stateListAnimator = null
                setOnClickListener { showPage(label, this) }
            }, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
        }
        addView(navigation, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))
        selectButton(0)
    }

    private fun showPage(label: String, selected: Button) {
        content.removeAllViews()
        content.addView(containerFor(label))
        selectButton(navigation.indexOfChild(selected))
        val page = pages.getValue(label)
        when (page) {
            is NativeOverviewView -> page.refresh()
            is NativeTransactionsView -> page.reload()
            is NativeReviewView -> page.reload()
        }
        NativeUi.styleTree(page)
    }

    private fun containerFor(label: String): ScrollView = pageContainers.getOrPut(label) {
        val page = pages.getOrPut(label) { pageFactories.getValue(label).invoke() }
        NativeUi.styleTree(page)
        pageContainer(page)
    }

    private fun pageContainer(page: View) = ScrollView(context).apply {
        isFillViewport = true
        addView(page, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))
    }

    private fun selectButton(index: Int) {
        for (position in 0 until navigation.childCount) {
            (navigation.getChildAt(position) as Button).apply {
                isSelected = position == index
                alpha = if (isSelected) 1f else 0.65f
                setTextColor(if (isSelected) NativeUi.green else NativeUi.muted)
                setTypeface(typeface, if (isSelected) Typeface.BOLD else Typeface.NORMAL)
            }
        }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
