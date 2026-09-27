# Android 交付架构

[简体中文](ANDROID.zh-CN.md) | [English](ANDROID.md)

实际设备验证步骤见 [Android 真机验收](ANDROID_ACCEPTANCE.zh-CN.md)；对应英文版为 [Android Device Acceptance](ANDROID_ACCEPTANCE.md)。

Android 版本必须继续使用统一账本 Schema、导入适配器、审核规则和便携归档，不另建移动端数据库或复制业务逻辑。

## 已确定边界

- 使用 Chaquopy 17.x 在 APK/AAB 内嵌 Python 3.10+ 账本内核；最低 Android API 24。
- Kotlin 通过 `beancount_dedup.android_bridge.dispatch` 直接传递 JSON 请求，不启动 localhost HTTP 服务。
- SQLite 数据库只能放在应用私有目录；升级不得删除，卸载行为遵循 Android 系统的数据生命周期。
- WebView 使用 `WebViewAssetLoader` 和 `https://appassets.androidplatform.net` 加载随包静态资源；关闭文件访问、内容访问、明文流量和生产调试，不加载任意远程页面。
- 原生文件选择使用 Storage Access Framework：单文件、多选文件及目录授权；Kotlin 读取用户明确选择的内容后，再以现有导入 API 所需的 Base64 负载送入统一内核。
- 导出使用系统创建文档界面，由用户明确选择保存位置；应用不申请“所有文件访问”权限。
- 正式更新必须保持 application ID、递增 versionCode，并使用同一 Android 应用签名身份或有效密钥轮换证明，避免卸载重装。

## 当前小阶段

本阶段已经提供最小 Kotlin/Gradle 工程、无网络桥接、仅允许应用内域名的 WebView 和静态资源白名单，并验证健康检查、统一 Schema 初始化、移动端新增/查询交易及路径拒绝。Android 调试应用可通过系统文件选择器选择单个文件、多个文件或文件夹；选择结果复用网页端批量导入队列，不支持、过大或读取失败的文件会按文件名提示。交易 CSV/JSON 和完整便携归档也可通过系统“创建文档”界面保存到用户选择的位置，全程不申请广泛存储权限。手动 GitHub Actions 只生成调试 APK，不发布也不签署正式版本。

Android APK/AAB 尚未形成可发布产物；不得把当前调试 APK 描述为正式发布就绪。
