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
    private val pages = linkedMapOf(
        "概览" to NativeOverviewView(context, client),
        "交易" to NativeTransactionsView(context, client),
        "审核" to NativeReviewView(context, client),
        "数据" to dataView,
    )
    private val pageContainers = pages.mapValues { pageContainer(it.value) }
    private val navigation = LinearLayout(context)

    init {
        orientation = VERTICAL
        content.addView(pageContainers.getValue("概览"))
        addView(content, LayoutParams(LayoutParams.MATCH_PARENT, 0, 1f))

        navigation.orientation = HORIZONTAL
        navigation.gravity = Gravity.CENTER
        navigation.setPadding(dp(4), dp(4), dp(4), dp(4))
        pages.forEach { (label, page) ->
            navigation.addView(Button(context).apply {
                text = label
                isAllCaps = false
                minHeight = dp(56)
                setOnClickListener { showPage(page, this) }
            }, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
        }
        addView(navigation, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))
        selectButton(0)
    }

    private fun showPage(page: View, selected: Button) {
        content.removeAllViews()
        val label = pages.entries.first { it.value === page }.key
        content.addView(pageContainers.getValue(label))
        selectButton(navigation.indexOfChild(selected))
        when (page) {
            is NativeOverviewView -> page.refresh()
            is NativeTransactionsView -> page.reload()
            is NativeReviewView -> page.reload()
        }
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
                setTypeface(typeface, if (isSelected) Typeface.BOLD else Typeface.NORMAL)
            }
        }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
