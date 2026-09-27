package io.github.ssh555.financialbeancount

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.TextView

object NativeUi {
    val ink = Color.rgb(23, 34, 29)
    val muted = Color.rgb(104, 117, 111)
    val paper = Color.rgb(243, 242, 236)
    val card = Color.rgb(255, 254, 250)
    val line = Color.rgb(220, 222, 216)
    val green = Color.rgb(35, 92, 70)
    val greenSoft = Color.rgb(220, 235, 226)
    val red = Color.rgb(162, 58, 50)

    fun dp(context: Context, value: Int) = (value * context.resources.displayMetrics.density).toInt()

    fun rounded(context: Context, color: Int, radius: Int = 14, stroke: Int = line) =
        GradientDrawable().apply {
            setColor(color)
            cornerRadius = dp(context, radius).toFloat()
            setStroke(dp(context, 1), stroke)
        }

    fun card(view: View, radius: Int = 18) {
        view.background = rounded(view.context, card, radius)
        view.elevation = dp(view.context, 2).toFloat()
    }

    fun styleTree(view: View) {
        when (view) {
            is EditText -> {
                view.setTextColor(ink)
                view.setHintTextColor(muted)
                view.typeface = Typeface.create("sans-serif", Typeface.NORMAL)
                view.background = rounded(view.context, Color.WHITE, 11)
                view.setPadding(dp(view.context, 12), 0, dp(view.context, 12), 0)
            }
            is Button -> styleButton(view)
            is TextView -> {
                view.setTextColor(if (view.tag == "featured") Color.WHITE else ink)
                val style = if (view.typeface?.isBold == true) Typeface.BOLD else Typeface.NORMAL
                view.typeface = Typeface.create("sans-serif", style)
            }
        }
        if (view is ViewGroup) {
            for (index in 0 until view.childCount) styleTree(view.getChildAt(index))
        }
    }

    fun styleButton(button: Button, primary: Boolean = false, danger: Boolean = false) {
        val label = button.text.toString()
        val isDanger = danger || label.contains("删除") || label.contains("排除")
        val isCard = label.contains('\n')
        button.isAllCaps = false
        button.typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        button.stateListAnimator = null
        button.backgroundTintList = ColorStateList.valueOf(Color.TRANSPARENT)
        button.background = rounded(
            button.context,
            when {
                isDanger -> Color.rgb(255, 247, 246)
                primary -> green
                isCard -> card
                else -> greenSoft
            },
            if (isCard) 15 else 11,
            if (isDanger) Color.rgb(228, 187, 183) else line,
        )
        button.setTextColor(if (primary) Color.WHITE else if (isDanger) red else if (isCard) ink else green)
        if (isCard) {
            button.gravity = android.view.Gravity.START or android.view.Gravity.CENTER_VERTICAL
            button.setPadding(dp(button.context, 14), dp(button.context, 10), dp(button.context, 14), dp(button.context, 10))
            (button.layoutParams as? ViewGroup.MarginLayoutParams)?.setMargins(0, dp(button.context, 5), 0, dp(button.context, 5))
        }
    }
}
