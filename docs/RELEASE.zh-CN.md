# Release 门禁与外部凭据

[简体中文](RELEASE.zh-CN.md) | [English](RELEASE.md)

仓库目前不自动发布 GitHub Release。桌面工作流首先生成供审查的产物；工作流成功不等于允许公开发布。

## 所有权与文档维护规则

代码签名证书、平台账号和更新签名密钥由实际发布者配置，最终用户无需配置。发布下游分支时，发布者必须使用自己的身份，并在构建中嵌入与自身更新私钥匹配的公钥。私钥、证书文件和密码只能存放在受保护的部署 Secret 中，不得提交、打印到日志或打入应用。

包格式、Secret/Variable 名称、签名或公证命令、更新资源名称、支持升级范围或 Release 门禁发生变化时，必须在同一提交中同步维护 README 和对应的中英文文档。预览构建无需发布凭据；选择 `signed_release` 后一律失败关闭，不允许测试证书或未签名回退。

## 发布者配置矩阵

| 范围 | GitHub 配置 | 配置者 | 状态 |
| --- | --- | --- | --- |
| 更新清单 | Variable `FINANCIAL_BEANCOUNT_UPDATE_PUBLIC_KEY`；Secret `FINANCIAL_BEANCOUNT_RELEASE_SIGNING_KEY` | 实际发布者 | 已实现；必须是匹配的 Ed25519 密钥对 |
| Windows | Secrets `FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE`、`FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE_PASSWORD`；Variables `FINANCIAL_BEANCOUNT_WINDOWS_TIMESTAMP_URL`、`FINANCIAL_BEANCOUNT_WINDOWS_PUBLISHER` | Windows 发布者 | 已实现；正式证书待配置 |
| macOS | Secrets `FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE`、`FINANCIAL_BEANCOUNT_MACOS_CERTIFICATE_PASSWORD`、`FINANCIAL_BEANCOUNT_APPLE_ID`、`FINANCIAL_BEANCOUNT_APPLE_APP_PASSWORD`；Variables `FINANCIAL_BEANCOUNT_MACOS_SIGNING_IDENTITY`、`FINANCIAL_BEANCOUNT_APPLE_TEAM_ID` | Apple Developer 账号持有者 | 工作流已实现；干净 Runner 验证待完成 |
| Linux | 随最终包格式定义专用签名密钥及配置名 | Linux 发布者 | 未实现，仍是发布阻塞项 |

证书续期、吊销和发布者交接属于部署操作。轮换前必须在候选构建中验证新信任链，按需更新固定公钥/身份，保留上一可信版本的回滚能力，并在发行说明中记录。证书过期或被吊销时不得通过关闭门禁绕过。

## 已实现门禁

- 可复现平台归档及 SHA-256 清单。
- Ed25519 更新清单签名和构建时嵌入的可信公钥。
- 安全下载、解压、原位替换、健康检查和回滚。
- 可恢复数据库迁移及 Windows/macOS/Linux 升级矩阵。
- 隐私和离线边界测试。
- 失败关闭的预览门禁：版本一致性、必要文档、目标归档及精确摘要。
- 严格发布门禁：签名更新清单、原生安装包及与安装包摘要绑定的系统签名证据。

Windows 和 macOS 的严格门禁只在对应 `signed_release` 作业中启用。Linux 在原生安装包和签名链完成前不得进入正式门禁。

## 完整私有账本验收

候选版本可对完整私有账单集执行导入、无歧义记录确认、单文件归档导出及全新数据库恢复校验：

```bash
python scripts/acceptance_full_ledger.py \
  --bills /path/to/private/statements \
  --output /path/to/new-empty-output-directory
```

账单目录、数据库、报告和归档不得进入 Git。已解压的受支持账单逐文件隔离处理，同目录 ZIP 原包明确跳过；不支持或损坏的内容必须按文件报告并阻止导出；有歧义的匹配候选保留待人工审核。成功结果生成 `complete-ledger.financial-beancount.zip` 和 `acceptance-report.json`，并验证该单文件可无损初始化移动端账本。

## Windows 发布链路

预览 MSI 按用户安装到 `%LOCALAPPDATA%\Programs\FinancialBeancount`，采用稳定 UpgradeCode 和变化的 ProductCode 原位升级。账本位于独立的 `%LOCALAPPDATA%\FinancialBeancount`，升级和卸载均不得删除。CI 会安装低版本、创建数据哨兵、升级当前版本并卸载，验证应用文件生命周期与账本保留。

正式作业依次签名并验证主程序、更新助手和 MSI，使用 SHA-256 与 HTTPS RFC 3161 时间戳，固定预期发布者，生成摘要绑定证据后运行严格门禁。凭据缺失、Base64/PFX 无效、密码错误、时间戳失败、信任链无效或发布者不匹配都会终止。

WiX 校验保持启用，仅抑制与本项目设计明确冲突的 ICE38、ICE64、ICE91（它们假设用户目录文件采用漫游或全机器组件规则）以及 ICE61（它拒绝有意支持的同版本预览重构包）。真实安装、升级、卸载和账本保留测试是这些精确抑制项的强制补偿门禁；CI 不使用全局跳过验证。

## macOS 发布链路

预览构建生成包含 `FinancialBeancount.app` 和 `/Applications` 链接的压缩只读 DMG，并在临时目录验证挂载、替换升级、移除和 Application Support 账本保留。

正式作业把 Developer ID Application 证书导入临时 Keychain，为应用启用强化运行时和安全时间戳，签名应用与 DMG，等待 `notarytool` 明确返回 `Accepted`，装订并验证票据，执行 Gatekeeper 评估，生成原生证据并进入严格门禁。临时证书和 Keychain 在任何退出路径都会删除。

## 当前发布阻塞项

- 由实际发布者配置并验证 Windows 与 Apple 正式凭据。
- macOS 签名、公证和 DMG 流程在干净 macOS Runner 上完成正向验证。
- 确定 Linux 包格式，完成签名、安装、升级、卸载与回滚验证。
- 所有目标平台必须能从每个仍受支持的正式版本原位升级且不删除用户账本。

在上述条件全部满足前，不得创建公开 Release。
