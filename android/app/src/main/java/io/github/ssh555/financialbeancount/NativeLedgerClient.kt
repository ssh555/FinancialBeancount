package io.github.ssh555.financialbeancount

import android.content.Context
import android.os.Handler
import android.os.Looper
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.util.concurrent.Executors

class NativeLedgerClient(context: Context) : AutoCloseable {
    private val appContext = context.applicationContext
    private val executor = Executors.newFixedThreadPool(3)
    private val main = Handler(Looper.getMainLooper())
    private val module by lazy {
        if (!Python.isStarted()) Python.start(AndroidPlatform(appContext))
        Python.getInstance().getModule("beancount_dedup.android_bridge")
    }

    fun request(
        method: String,
        target: String,
        body: JSONObject? = null,
        callback: (Result<JSONObject>) -> Unit,
    ) {
        executor.execute {
            val result = runCatching {
                val request = JSONObject().put("method", method).put("target", target)
                if (body != null) request.put("body", body)
                val database = appContext.getDatabasePath("ledger.sqlite3").absolutePath
                val response = JSONObject(module.callAttr("dispatch", database, request.toString()).toString())
                if (response.getInt("status") !in 200..299) {
                    error(response.optJSONObject("body")?.optJSONObject("error")?.optString("message") ?: "本地账本请求失败")
                }
                response
            }
            main.post { callback(result) }
        }
    }

    override fun close() {
        executor.shutdownNow()
    }
}
