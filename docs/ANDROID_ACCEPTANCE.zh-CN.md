# Android 真机验收

[简体中文](ANDROID_ACCEPTANCE.zh-CN.md) | [English](ANDROID_ACCEPTANCE.md)

本清单用于当前调试 APK 的功能验收，不代表正式发布签名、商店分发或升级链路已经完成。最低系统版本为 Android 7.0（API 24）。

## 获取并安装调试 APK

1. 在 GitHub Actions 打开 **Android debug build**，手动运行 `main` 分支并等待成功。
2. 在运行详情页的 Artifacts 下载 `FinancialBeancount-android-debug`，解压得到 `app-debug.apk`。
3. 将 APK 传到测试设备并允许本次来源安装，或连接 ADB 后运行：

```bash
adb install app-debug.apk
```

GitHub Actions 调试包仅用于当前功能验收。不同运行生成的调试签名可能不同，因此不得用它验证原位升级；正式 Release 必须使用发布者长期保存的同一签名身份、递增 `versionCode`，并通过升级后账本保留测试。

## 准备单个完整账本文件

在桌面端对已经准备好的完整账单目录运行：

```bash
python scripts/acceptance_full_ledger.py \
  --bills /path/to/private/statements \
  --output /path/to/new-empty-output-directory
```

只有当报告没有未处理文件时，才使用生成的 `complete-ledger.financial-beancount.zip`。账单、数据库、报告和归档都属于私有数据，不得上传到 GitHub 或作为 Actions 产物。

进入真机验收前还应对生成的数据库运行统计守恒校验：

```bash
python scripts/validate_complete_ledger.py \
  --database /path/to/complete-ledger.sqlite3 \
  --output /path/to/complete-ledger-validation.json
```

校验报告中的 `summary.net_cash_flow` 是账期内累计收支差额，不是当前余额。当前可识别余额查看
`account_balance.known_balance`：它使用银行原始流水中的最新活期余额，并叠加可明确识别的银行内部产品
（目前为招商银行朝朝宝、工商银行天天盈）。外部天天基金等基金平台，以及无法从账单取得余额的支付账户，
不计入该数值。验收时应同时核对 `cash_accounts`、`internal_products` 和各自的截至日期。

再生成只读数据质量审计报告。该步骤只标记疑似重复、归并候选与基金/理财流向，不会自动修改账本：

```bash
python scripts/audit_complete_ledger.py \
  --database /path/to/complete-ledger.sqlite3 \
  --output /path/to/complete-ledger-data-quality.json
```

`high` 只表示优先人工核对，不表示可以自动删除；相同金额与余额也可能来自朝朝宝自动赎回后的真实连续交易。

再运行移动端主要读取路径的性能基线；任一项目超过报告中的阈值时，不进入真机验收：

```bash
python scripts/benchmark_mobile.py \
  --database /path/to/complete-ledger.sqlite3 \
  --output /path/to/mobile-performance.json
```

## 真机闭环

1. 首次启动后关闭网络，确认概览、交易、审核和设置仍能打开。
2. 进入“设置 → 数据与迁移 → 恢复完整归档”，确认覆盖提示后只选择上述 ZIP 文件。
3. 确认提示“完整账本已恢复”，抽查日期、金额、商户、分类、来源数及审核队列；至少搜索三笔已知交易。
   同时确认概览“账户余额”与桌面校验报告一致，并且没有把“收支差额”当成余额。
4. 新增一笔测试交易，修改后软删除，再从回收站恢复，确认各步骤均可见。
5. 分别导出 CSV、JSON 和完整归档，确认系统保存界面可选择目录且文件可以再次打开。
6. 把移动端导出的完整归档传回桌面，执行校验并恢复到一个不存在的新数据库路径：

```bash
python -m beancount_dedup.archive_cli inspect --archive /path/to/mobile-export.zip
python -m beancount_dedup.archive_cli import \
  --archive /path/to/mobile-export.zip \
  --database /path/to/new-mobile-restored.sqlite3
```

7. 可另选少量账单测试“单文件、多个文件、文件夹”三个入口。扩展名不支持、过大、内容不受支持或损坏的文件必须按文件名显示为未加入或未处理，不能造成部分账本写入。

## 通过标准

- 全程无需网络服务、网络权限或“所有文件访问”权限。
- 单个完整归档可恢复，损坏归档失败后原账本仍可使用。
- 桌面验收报告中的核心数量与移动端抽查结果一致；新增测试交易及其审计操作能够随移动端归档再次恢复。
- CSV、JSON 与完整归档均能保存到用户选择的位置。
- 应用无崩溃、空白页、静默跳过文件或要求卸载重装的正式升级设计。

记录设备型号、Android 版本、APK 对应提交、验收时间、通过项和失败项即可，不需要引入额外测试管理系统。
