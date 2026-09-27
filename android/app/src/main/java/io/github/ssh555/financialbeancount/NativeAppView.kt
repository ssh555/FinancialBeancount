package io.github.ssh555.financialbeancount

import android.content.Context
import android.content.res.ColorStateList
import android.view.Menu
import android.view.View
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import com.google.android.material.bottomnavigation.BottomNavigationView

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
    private val navigation = BottomNavigationView(context)
    private val navigationItems = linkedMapOf(
        "概览" to Pair(View.generateViewId(), R.drawable.ic_overview),
        "交易" to Pair(View.generateViewId(), R.drawable.ic_transactions),
        "审核" to Pair(View.generateViewId(), R.drawable.ic_review),
        "数据" to Pair(View.generateViewId(), R.drawable.ic_data),
    )

    init {
        orientation = VERTICAL
        setBackgroundColor(NativeUi.paper)
        content.addView(containerFor("概览"))
        addView(content, LayoutParams(LayoutParams.MATCH_PARENT, 0, 1f))

        navigation.setBackgroundColor(NativeUi.card)
        navigation.elevation = dp(10).toFloat()
        navigation.itemIconTintList = navigationColors()
        navigation.itemTextColor = navigationColors()
        navigation.labelVisibilityMode = BottomNavigationView.LABEL_VISIBILITY_LABELED
        navigationItems.forEach { (label, item) ->
            navigation.menu.add(Menu.NONE, item.first, Menu.NONE, label).setIcon(item.second)
        }
        navigation.setOnItemSelectedListener { item ->
            navigationItems.entries.firstOrNull { it.value.first == item.itemId }?.key?.let(::showPage)
            true
        }
        addView(navigation, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))
        navigation.selectedItemId = navigationItems.getValue("概览").first
        navigation.post { NativeUi.styleTree(navigation) }
    }

    private fun showPage(label: String) {
        content.removeAllViews()
        content.addView(containerFor(label))
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

    private fun navigationColors() = ColorStateList(
        arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf()),
        intArrayOf(NativeUi.green, NativeUi.muted),
    )

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
