package io.github.ssh555.financialbeancount

import android.annotation.SuppressLint
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import androidx.activity.ComponentActivity
import androidx.webkit.WebViewClientCompat
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.ByteArrayInputStream

private const val APP_ORIGIN = "https://appassets.androidplatform.net"

class MainActivity : ComponentActivity() {
    private lateinit var bridge: PyObject
    private lateinit var webView: WebView

    @SuppressLint("SetJavaScriptEnabled", "AddJavascriptInterface")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        bridge = Python.getInstance().getModule("beancount_dedup.android_bridge")

        webView = WebView(this)
        setContentView(webView)
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
        }
        webView.addJavascriptInterface(LedgerJavascriptBridge(), "FinancialBeancountNative")
        webView.webViewClient = LocalOnlyClient()
        webView.loadUrl("$APP_ORIGIN/index.html")
    }

    override fun onDestroy() {
        webView.removeJavascriptInterface("FinancialBeancountNative")
        webView.destroy()
        super.onDestroy()
    }

    private inner class LedgerJavascriptBridge {
        @JavascriptInterface
        fun request(requestJson: String): String {
            val database = getDatabasePath("ledger.sqlite3").absolutePath
            return bridge.callAttr("dispatch", database, requestJson).toString()
        }
    }

    private inner class LocalOnlyClient : WebViewClientCompat() {
        override fun shouldInterceptRequest(
            view: WebView,
            request: WebResourceRequest,
        ): WebResourceResponse? {
            if (request.url.scheme != "https" || request.url.host != "appassets.androidplatform.net") {
                return blockedResponse()
            }
            val path = request.url.path ?: "/"
            return try {
                val bytes = bridge.callAttr("web_asset", path).toJava(ByteArray::class.java)
                val contentType = bridge.callAttr("web_asset_content_type", path).toString()
                val parts = contentType.split(";", limit = 2)
                WebResourceResponse(
                    parts[0],
                    if (parts.size == 2) "UTF-8" else null,
                    ByteArrayInputStream(bytes),
                )
            } catch (_: Exception) {
                blockedResponse()
            }
        }

        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
            request.url.scheme != "https" || request.url.host != "appassets.androidplatform.net"

        private fun blockedResponse() = WebResourceResponse(
            "text/plain",
            "UTF-8",
            404,
            "Not Found",
            mapOf("Cache-Control" to "no-store"),
            ByteArrayInputStream(ByteArray(0)),
        )
    }
}
