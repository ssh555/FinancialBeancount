package io.github.ssh555.financialbeancount

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/** Semantic design tokens shared by every Compose screen and future skin. */
object LedgerColors {
    val Ink = Color(0xFF17221D)
    val Muted = Color(0xFF68756F)
    val Paper = Color(0xFFF3F2EC)
    val Card = Color(0xFFFFFEFA)
    val Line = Color(0xFFDCDed8)
    val Primary = Color(0xFF235C46)
    val PrimaryContainer = Color(0xFFDCEBE2)
    val Danger = Color(0xFFA23A32)
}

private val LedgerColorScheme = lightColorScheme(
    primary = LedgerColors.Primary,
    onPrimary = Color.White,
    primaryContainer = LedgerColors.PrimaryContainer,
    onPrimaryContainer = Color(0xFF173D2F),
    background = LedgerColors.Paper,
    onBackground = LedgerColors.Ink,
    surface = LedgerColors.Card,
    onSurface = LedgerColors.Ink,
    outline = LedgerColors.Line,
    error = LedgerColors.Danger,
)

@Composable
fun FinancialBeancountTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = LedgerColorScheme,
        typography = MaterialTheme.typography.copy(
            headlineLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold, fontSize = 30.sp),
            titleLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold, fontSize = 22.sp),
            bodyLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 16.sp),
            bodyMedium = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 14.sp),
            labelLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold, fontSize = 14.sp),
        ),
        content = content,
    )
}
