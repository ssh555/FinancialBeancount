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
    private val responseCache = object : LinkedHashMap<String, String>(64, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, String>?): Boolean = size > 64
    }
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
        val cacheKey = if (method == "GET" && body == null) target else null
        val cached = synchronized(responseCache) { cacheKey?.let(responseCache::get) }
        if (cached != null) {
            main.post { callback(Result.success(JSONObject(cached))) }
            return
        }
        executor.execute {
            val result = runCatching {
                val request = JSONObject().put("method", method).put("target", target)
                if (body != null) request.put("body", body)
                val database = appContext.getDatabasePath("ledger.sqlite3").absolutePath
                val response = JSONObject(module.callAttr("dispatch", database, request.toString()).toString())
                if (response.getInt("status") !in 200..299) {
                    error(response.optJSONObject("body")?.optJSONObject("error")?.optString("message") ?: "本地账本请求失败")
                }
                if (cacheKey != null) synchronized(responseCache) { responseCache[cacheKey] = response.toString() }
                else if (method != "GET") invalidateCache()
                response
            }
            main.post { callback(result) }
        }
    }

    fun invalidateCache() {
        synchronized(responseCache) { responseCache.clear() }
    }

    override fun close() {
        executor.shutdownNow()
    }
}
