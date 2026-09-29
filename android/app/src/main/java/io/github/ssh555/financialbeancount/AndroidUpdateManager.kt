package io.github.ssh555.financialbeancount

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

private const val RELEASE_API = "https://api.github.com/repos/ssh555/FinancialBeancount/releases/latest"
private const val MAX_METADATA_BYTES = 1024 * 1024
private const val MAX_APK_BYTES = 200L * 1024 * 1024

data class AndroidUpdateInfo(
    val version: String,
    val notes: String,
    val apkName: String,
    val apkUrl: String,
    val apkSize: Long,
    val checksumUrl: String,
)

class AndroidUpdateManager(private val context: Context) {
    fun check(): AndroidUpdateInfo? {
        val release = JSONObject(downloadText(RELEASE_API, MAX_METADATA_BYTES))
        if (release.optBoolean("draft") || release.optBoolean("prerelease")) return null
        val version = release.getString("tag_name").removePrefix("v")
        if (!isNewer(version, BuildConfig.VERSION_NAME)) return null
        val expectedApk = "FinancialBeancount-android-$version.apk"
        val assets = release.getJSONArray("assets")
        var apk: JSONObject? = null
        var checksum: JSONObject? = null
        for (index in 0 until assets.length()) {
            val item = assets.getJSONObject(index)
            when (item.getString("name")) {
                expectedApk -> apk = item
                "$expectedApk.sha256" -> checksum = item
            }
        }
        val selectedApk = apk ?: error("此版本缺少 Android APK")
        val selectedChecksum = checksum ?: error("此版本缺少 APK 校验文件")
        val size = selectedApk.getLong("size")
        require(size in 1..MAX_APK_BYTES) { "APK 文件大小无效" }
        return AndroidUpdateInfo(
            version,
            release.optString("body"),
            expectedApk,
            https(selectedApk.getString("browser_download_url")),
            size,
            https(selectedChecksum.getString("browser_download_url")),
        )
    }

    fun download(update: AndroidUpdateInfo, onProgress: (Int) -> Unit = {}): File {
        val checksum = downloadText(update.checksumUrl, 4096).trim().split(Regex("\\s+"))
        require(checksum.size >= 2 && checksum[0].matches(Regex("[0-9a-fA-F]{64}"))) { "APK 校验文件无效" }
        require(checksum.last().substringAfterLast('/').removePrefix("*") == update.apkName) { "APK 校验文件名不匹配" }
        val directory = File(context.cacheDir, "updates").apply { mkdirs() }
        directory.listFiles()?.forEach { stale -> stale.delete() }
        val target = File(directory, update.apkName)
        val connection = open(update.apkUrl)
        try {
            require(connection.responseCode == HttpURLConnection.HTTP_OK) { "APK 下载失败：HTTP ${connection.responseCode}" }
            val declared = connection.contentLengthLong
            require(declared < 0 || declared == update.apkSize) { "APK 下载大小与 Release 信息不一致" }
            val digest = MessageDigest.getInstance("SHA-256")
            connection.inputStream.use { input ->
                target.outputStream().use { output ->
                    val buffer = ByteArray(64 * 1024)
                    var total = 0L
                    var reportedPercent = -1
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        total += count
                        require(total <= MAX_APK_BYTES && total <= update.apkSize) { "APK 下载大小超限" }
                        output.write(buffer, 0, count)
                        digest.update(buffer, 0, count)
                        val percent = ((total * 100) / update.apkSize).toInt().coerceIn(0, 100)
                        if (percent != reportedPercent) {
                            reportedPercent = percent
                            onProgress(percent)
                        }
                    }
                    require(total == update.apkSize) { "APK 下载不完整" }
                }
            }
            val actual = digest.digest().joinToString("") { "%02x".format(it) }
            require(actual.equals(checksum[0], ignoreCase = true)) { "APK SHA-256 校验失败" }
            return target
        } catch (error: Exception) {
            target.delete()
            throw error
        } finally {
            connection.disconnect()
        }
    }

    fun install(apk: File): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !context.packageManager.canRequestPackageInstalls()) {
            context.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}")))
            return false
        }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.updates", apk)
        context.startActivity(Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        })
        return true
    }

    fun cleanupDownloadedPackages() {
        File(context.cacheDir, "updates").listFiles()?.forEach { it.delete() }
        File(context.cacheDir, "updates").delete()
    }

    private fun downloadText(url: String, limit: Int): String {
        val connection = open(https(url))
        try {
            require(connection.responseCode == HttpURLConnection.HTTP_OK) { "更新信息请求失败：HTTP ${connection.responseCode}" }
            connection.inputStream.use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    require(output.size() + count <= limit) { "更新信息超过大小限制" }
                    output.write(buffer, 0, count)
                }
                return output.toString(Charsets.UTF_8.name())
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun open(url: String) = (URL(https(url)).openConnection() as HttpURLConnection).apply {
        connectTimeout = 10_000
        readTimeout = 30_000
        instanceFollowRedirects = true
        setRequestProperty("Accept", "application/vnd.github+json")
        setRequestProperty("User-Agent", "FinancialBeancount/${BuildConfig.VERSION_NAME}")
    }

    private fun https(value: String): String {
        require(value.startsWith("https://")) { "更新地址必须使用 HTTPS" }
        return value
    }

    private fun isNewer(candidate: String, current: String): Boolean {
        fun parse(value: String): List<Int> {
            require(value.matches(Regex("\\d+\\.\\d+\\.\\d+"))) { "无法识别更新版本：$value" }
            return value.split('.').map(String::toInt)
        }
        val left = parse(candidate)
        val right = parse(current)
        return left.zip(right).firstOrNull { it.first != it.second }?.let { it.first > it.second } ?: false
    }
}
