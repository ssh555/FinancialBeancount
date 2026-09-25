# Beancount Multi-Platform Bill Deduplicator

> A Beancount-based double-entry accounting tool for deduplicating and converting bills from Alipay, WeChat Pay, and bank cards.

[![CI](https://img.shields.io/github/actions/workflow/status/CacinieP/FinancialBeancount/ci.yml?branch=main&style=flat-square)](https://github.com/CacinieP/FinancialBeancount/actions)
[![License](https://img.shields.io/github/license/CacinieP/FinancialBeancount?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square)](requirements.txt)

**[Beancount](https://github.com/beancount/beancount)** is an excellent plain-text double-entry accounting system. This project is an independent third-party tool for converting bills from China's major payment platforms (Alipay, WeChat Pay) and banks into Beancount format, with smart deduplication.

---

## Who This Is For

- People already using Beancount or migrating to plain-text double-entry accounting
- People with bills from Alipay, WeChat Pay, and bank cards who worry about duplicate imports
- People who want to clean bills locally without uploading financial data to third-party services
- People who need auditable intermediate results instead of a black-box export file

## Features

- **Bundled local web app**: Mobile-first dashboard, unique transaction browser, and complete review queues with no cloud dependency
- **Installable offline shell**: The local UI can be installed from a modern browser as a PWA; sensitive API responses are never cached
- **Three-level fingerprint deduplication**: L1 (exact) / L2 (loose) / L3 (fuzzy) matching strategies
- **Multi-format support**: CSV, XLSX, PDF auto-conversion
- **Smart account classification**: Auto-classification based on Beancount best practices
- **Platform priority**: Alipay > WeChat > Bank (by information completeness)
- **Special-case detection**: Internal transfers, cross-midnight early-morning transactions, consecutive same-amount transaction protection

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/CacinieP/FinancialBeancount.git
cd FinancialBeancount

# 2. Install dependencies (optional, for XLSX/PDF support)
pip install -r requirements.txt

# 3. Place your statement files in input/ folder
cp /path/to/your/statements/* input/

# 4. Run the pipeline
python example_usage.py

# 5. Check the output
# output/output.beancount        - Deduplicated transactions
# output/duplicate_report.beancount - Duplicate transaction report
```

### Local Web App

The installed package includes a responsive web client served by the local API:

```bash
financial-beancount-api --database ledger.sqlite3 --open-browser
# Or open http://127.0.0.1:8765 manually
```

The app provides statistics; canonical transaction creation, search, full editing, auditable soft deletion and restoration, plus JSON/CSV export; official statement import and import history through the adapter registry; complete portable archive download; transaction details (including all linked sources); and manual review queues for overlapping imports, candidate merges, refunds, and classifications. Statement import accepts one file, multiple selected files, or a folder filtered into a visible batch queue. Every queued file keeps its own format, source account, result, and review session, so one malformed file does not block the others. Extension and size checks run before queueing; strict content validation runs during each isolated import, and files whose contents are not a supported statement are listed by name as unprocessed without partial ledger writes. Its installable application shell works offline after the first visit; ledger data always comes directly from the local API and is deliberately excluded from browser caches. Immutable raw observations are never deleted by canonical transaction operations.

To access the UI from another device on your private network, bind to the computer's LAN address and set `FINANCIAL_BEANCOUNT_API_TOKEN`. Do not expose the service to the public internet.

### Desktop Application

An installed Python package also provides a native desktop controller. It creates the ledger under
the operating system's per-user application-data directory, starts the local service on an available
loopback port, and opens the web interface. Its **检查更新** button performs an explicitly requested
check against the project's latest GitHub Release. Downloading and installation each require a
separate confirmation; the archive is staged outside the application, checked against its published
SHA-256, safely extracted, and handed to an external helper only after the application exits. The
helper retains the previous application binaries and rolls back unless the new local service reports
that it is healthy;
the ledger database stays in the per-user data directory. Set `FINANCIAL_BEANCOUNT_UPDATE_API=off`
to disable checks, or set it to an alternative HTTPS metadata endpoint for a downstream build:

```bash
financial-beancount
```

Maintainers can produce a self-contained application directory with
`pyinstaller --clean --noconfirm FinancialBeancount.spec`. The manual GitHub Actions workflow builds
unsigned Windows, macOS, and Linux ZIP artifacts plus SHA-256 manifests for validation. The workflow
also smoke-tests the packaged update helper. Platform signatures and signed installers remain
release gates, so downloadable releases are intentionally not published yet.

Official update assets use an Ed25519 signature over the exact `.sha256` manifest. The desktop app
verifies that signature with a public key embedded at build time before it trusts the hash or
downloads the archive. The desktop workflow's `signed_release` mode requires both the repository
variable `FINANCIAL_BEANCOUNT_UPDATE_PUBLIC_KEY` (base64 raw 32-byte public key) and the GitHub
Actions secret `FINANCIAL_BEANCOUNT_RELEASE_SIGNING_KEY` (base64 raw 32-byte private key). The build
fails if either credential is absent, malformed, or the keys do not match. Private keys must never be
committed; ordinary development artifacts remain unsigned and are not accepted by the updater.

Before exiting for an in-place update, the desktop controller probes both the installation directory
and its parent. Writable installations continue normally. On Windows, a protected installation can
launch the already-staged helper through the standard UAC prompt; declining UAC leaves the running
application untouched. Other permission failures show the verified unpacked directory and explicit
manual replacement instructions. The ledger database remains in its per-user data directory and is
never part of the binary swap. If a late helper failure occurs after exit, the retained application is
started again and the diagnostic remains in `install-error.log`.

CI also runs a release-upgrade gate on Windows, macOS and Linux. The matrix performs the real binary
directory swap and then opens representative ledgers from every supported schema generation (8, 9
and current 10), checking migration backups and preserved canonical data. An injected migration
failure must leave the old database schema intact and roll the application binary back. Each future
published version must remain represented in this matrix until its upgrade support window ends.

The release privacy boundary is documented in [`docs/PRIVACY.md`](docs/PRIVACY.md). There is no
telemetry or automatic ledger upload: only a user-triggered update check can make an outbound request,
and automated gates restrict that client to the updater. API responses are never browser-cached, the
service worker caches only same-origin application-shell files, and the web UI uses a restrictive
Content Security Policy.

Maintainer-facing publication blockers and the external code-signing credentials that are still
required are recorded in [`docs/RELEASE.md`](docs/RELEASE.md). Until those platform signatures and
installers are implemented and verified, workflow artifacts remain development previews rather than
public Releases.

### Recoverable Database Upgrades

Existing Schema 8 or 9 ledgers are upgraded transactionally to the current schema. Before any
migration begins, the application writes and reopens a checksummed backup under the ledger's
`backups` directory. A failed migration rolls back all schema changes, keeps the backup and original
database, records a startup diagnostic, and offers an explicit restore action in the desktop
controller. The same recovery path is available while the application is closed:

```bash
financial-beancount-backup inspect --backup path/to/backup.financial-beancount.zip
financial-beancount-backup restore --backup path/to/backup.financial-beancount.zip --database ledger.sqlite3 --overwrite
```

Databases newer than the running application, databases older than the supported migration floor,
and unversioned non-empty databases are refused without modification.

### Unified Ledger Schema and Statement Adapters

All providers write the same `raw_transactions` observation schema and the same
`canonical_transactions` economic-transaction schema. Provider-only columns remain losslessly in
`original_row_json`; no provider receives its own database tables. Known source identifiers remain
compatible with the `Platform` enum, while adapters may use a normalized stable string such as
`example-bank` without changing the enum or database schema.

`StatementAdapter` is the public format boundary. An adapter validates its own file content,
converts rows to `RawTransaction`, then calls the narrow `StatementImportContext.persist()` service;
matching, review, CRUD, statistics, backup and export continue to operate on the unified models.
Built-in WeChat, Alipay, CMB and ICBC parsing is registered outside the core importer. Contract tests
prove that a separately defined source can be registered and persisted without core or schema edits.

## Project Structure

```
FinancialBeancount/
├── beancount_dedup/       # Main package
│   ├── models.py          # Data models
│   ├── fingerprinter.py   # Three-level fingerprint hashing
│   ├── deduplicator.py    # Deduplication engine
│   ├── account_classifier.py  # Intelligent account classification
│   ├── converters/        # Format converters (PDF/XLSX→CSV)
│   ├── parsers/           # Platform-specific parsers
│   └── exporters/         # Beancount format exporter
├── test_data/             # Sample anonymized data
├── input/                 # User statements (not in git)
├── output/                # Generated output (not in git)
└── example_usage.py       # Usage example
```

## Usage

### Python API

```python
from beancount_dedup import DeduplicationEngine
from beancount_dedup.parsers.alipay_parser import AlipayParser
from beancount_dedup.exporters.beancount import BeancountExporter

# Parse statements
alipay_txs = AlipayParser().parse("alipay_202401.csv").transactions

# Deduplicate
engine = DeduplicationEngine()
engine.add_transactions(alipay_txs)
unique_txs = engine.get_unique_transactions()

# Export to Beancount format
exporter = BeancountExporter()
exporter.export(unique_txs, output_path="output.beancount")
```

### Command Line

```bash
# Process all files in input/ folder
python example_usage.py
```

## Account Classification

This project uses Beancount best practices for account hierarchy:

```
Assets:Current:Digital:Alipay    # Alipay wallet
Assets:Current:Digital:WeChat    # WeChat wallet
Assets:Current:Bank:CMB          # China Merchants Bank

Expenses:Food:Restaurant         # Restaurants
Expenses:Food:Delivery           # Food delivery
Expenses:Transport:Private       # Taxi/Didi
Expenses:Shopping:Online         # Online shopping (JD/Taobao)
Expenses:Entertainment:Subscription  # Subscriptions (Netflix, etc.)
```

## Supported Platforms

| Platform | Format | Status |
|----------|--------|--------|
| Alipay | CSV | ✅ Fully supported |
| WeChat Pay | CSV | ✅ Fully supported |
| Bank Cards | CSV | ✅ Generic format |
| Excel (XLSX/XLS) | → CSV | ✅ Auto-conversion |
| PDF | → CSV | ⚠️ Requires `pdfplumber` |

## Testing

```bash
# Unit tests
python test_dedup.py

# E2E tests
python test_e2e_pipeline.py

# Test with sample data
cp test_data/*.csv input/
python example_usage.py
```

## Deduplication Strategy

| Level | Time Window | Description |
|-------|-------------|-------------|
| L1 | 2 minutes | Exact match: date + amount + normalized counterparty |
| L2 | 2 minutes | Loose match: date + amount (ignore name variations) |
| L3 | 1 day | Fuzzy match: cross-day / fee scenarios (marked for review) |

## Privacy & Security

- **All processing is local** — No data is sent to external servers
- **input/ and output/ folders are excluded from git** — Your financial data never leaves your machine
- **Sample test data is anonymized** — No real personal information in the repository
- **Review-before-import workflow** — Fuzzy matches are reported for manual review instead of being silently discarded

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## Acknowledgments

- [Beancount](https://github.com/beancount/beancount) by Martin Blais — The excellent plain text double-entry accounting system that inspired this project
- [Beancount Documentation](https://beancount.github.io/docs/) — Comprehensive documentation and best practices
- All contributors to the Beancount ecosystem

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Disclaimer

This is an independent third-party tool and is NOT officially affiliated with, endorsed by, or connected to:
- Alipay or Ant Group
- WeChat Pay or Tencent
- Any financial institutions mentioned

This tool is provided for educational and personal finance management purposes. The authors are not responsible for any financial decisions made based on the output of this software.

## Links

- [Beancount Official Repository](https://github.com/beancount/beancount)
- [Beancount Documentation](https://beancount.github.io/docs/)
- [External Contributions & Tools](https://beancount.github.io/docs/external_contributions.html)
- [Plain Text Accounting](https://plaintextaccounting.org/)
- [Upstream source repository](https://github.com/CacinieP/FinancialBeancount)

---

# Beancount 多平台账单去重工具

> 基于 Beancount 复式记账规范的多平台账单去重工具，支持支付宝、微信、银行卡账单的去重与格式转换。

[![CI](https://img.shields.io/github/actions/workflow/status/CacinieP/FinancialBeancount/ci.yml?branch=main&style=flat-square)](https://github.com/CacinieP/FinancialBeancount/actions)
[![License](https://img.shields.io/github/license/CacinieP/FinancialBeancount?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square)](requirements.txt)

**[Beancount](https://github.com/beancount/beancount)** 是一个优秀的纯文本复式记账系统。本项目是一个独立的第三方工具，用于将中国主流支付平台（支付宝、微信支付）和银行账单转换为 Beancount 格式，并智能去重。

---

## 适合谁

- 已经在用 Beancount 或准备迁移到纯文本复式记账的人
- 同时有支付宝、微信支付、银行卡账单，担心重复导入的人
- 想在本地完成账单清洗，不希望把财务数据上传到第三方服务的人
- 需要保留可审计中间结果，而不是只拿到一个黑箱导出文件的人

## 功能特性

- **内置本地 Web 应用**：移动端优先的统计概览、唯一交易浏览和完整人工审核队列，不依赖云服务
- **可安装离线壳层**：现代浏览器可将本地界面安装为 PWA；敏感 API 响应不会进入离线缓存
- **三级哈希指纹去重**：L1(精确) / L2(宽松) / L3(模糊) 匹配策略
- **多格式支持**：CSV、XLSX、PDF 自动转换
- **智能账户分类**：基于 Beancount 最佳实践的自动分类
- **平台优先级**：支付宝 > 微信 > 银行（信息完整度优先）
- **特殊场景识别**：内部转账、跨天凌晨交易、连续相同金额交易保护

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/CacinieP/FinancialBeancount.git
cd FinancialBeancount

# 2. 安装依赖（可选，XLSX/PDF 支持需要）
pip install -r requirements.txt

# 3. 将账单文件放入 input/ 目录
cp /path/to/your/statements/* input/

# 4. 运行处理流程
python example_usage.py

# 5. 查看输出
# output/output.beancount        - 去重后的交易
# output/duplicate_report.beancount - 重复交易报告
```

### 本地 Web 应用

安装后的软件包自带响应式界面，由本地 API 直接提供：

```bash
financial-beancount-api --database ledger.sqlite3 --open-browser
# 也可以手动打开 http://127.0.0.1:8765
```

界面支持统计概览；唯一交易的新增、搜索、完整修改、可审计软删除与恢复，以及 JSON/CSV 导出；通过适配器注册表导入官方账单并查看导入历史；下载包含全部数据与审计记录的便携归档；唯一交易详情（含全部关联来源）；以及重叠导入、候选归并、退款和分类的人工审核队列。首次访问后，可安装的应用壳层能够离线打开；账本数据始终从本地 API 实时读取，并明确排除在浏览器缓存之外。唯一交易的操作永远不会删除不可变的原始观察记录。

如需在私人局域网内从另一台设备访问，请绑定电脑的局域网地址并设置 `FINANCIAL_BEANCOUNT_API_TOKEN`。不要把服务直接暴露到公网。

### 桌面应用

安装 Python 软件包后还会提供原生桌面控制器。它会把账本放入操作系统的当前用户应用数据目录，
在可用的本机回环端口启动服务并自动打开 Web 界面：

```bash
financial-beancount
```

维护者可使用 `pyinstaller --clean --noconfirm FinancialBeancount.spec` 生成自包含应用目录。
手动触发的 GitHub Actions 工作流可构建未签名的 Windows、macOS 和 Linux 验证产物；带签名安装器和
自动更新属于正式发布门禁，目前不会提前发布。

## 项目结构

```
FinancialBeancount/
├── beancount_dedup/       # 主包
│   ├── models.py          # 数据模型
│   ├── fingerprinter.py   # 三级指纹哈希
│   ├── deduplicator.py    # 去重引擎
│   ├── account_classifier.py  # 智能账户分类
│   ├── converters/        # 格式转换器 (PDF/XLSX→CSV)
│   ├── parsers/           # 平台专用解析器
│   └── exporters/         # Beancount 格式导出器
├── test_data/             # 匿名化样本数据
├── input/                 # 用户账单（不在 git 中）
├── output/                # 生成输出（不在 git 中）
└── example_usage.py       # 使用示例
```

## 使用示例

### Python API

```python
from beancount_dedup import DeduplicationEngine
from beancount_dedup.parsers.alipay_parser import AlipayParser
from beancount_dedup.exporters.beancount import BeancountExporter

# 解析账单
alipay_txs = AlipayParser().parse("alipay_202401.csv").transactions

# 去重
engine = DeduplicationEngine()
engine.add_transactions(alipay_txs)
unique_txs = engine.get_unique_transactions()

# 导出为 Beancount 格式
exporter = BeancountExporter()
exporter.export(unique_txs, output_path="output.beancount")
```

### 命令行

```bash
# 处理 input/ 目录下的所有文件
python example_usage.py
```

## 账户分类

本项目使用 Beancount 最佳实践的账户层级：

```
Assets:Current:Digital:Alipay    # 支付宝钱包
Assets:Current:Digital:WeChat    # 微信钱包
Assets:Current:Bank:CMB          # 招商银行

Expenses:Food:Restaurant         # 餐厅
Expenses:Food:Delivery           # 外卖
Expenses:Transport:Private       # 出租车/滴滴
Expenses:Shopping:Online         # 网购（京东/淘宝）
Expenses:Entertainment:Subscription  # 订阅（Netflix 等）
```

## 支持平台

| 平台 | 格式 | 状态 |
|------|------|------|
| 支付宝 | CSV | ✅ 完全支持 |
| 微信支付 | CSV | ✅ 完全支持 |
| 银行卡 | CSV | ✅ 通用格式 |
| Excel (XLSX/XLS) | → CSV | ✅ 自动转换 |
| PDF | → CSV | ⚠️ 需安装 `pdfplumber` |

## 测试

```bash
# 单元测试
python test_dedup.py

# 端到端测试
python test_e2e_pipeline.py

# 使用样本数据测试
cp test_data/*.csv input/
python example_usage.py
```

## 去重策略

| 级别 | 时间窗口 | 说明 |
|------|----------|------|
| L1 | 2 分钟 | 精确匹配：日期 + 金额 + 归一化交易对方 |
| L2 | 2 分钟 | 宽松匹配：日期 + 金额（忽略名称变体） |
| L3 | 1 天 | 模糊匹配：跨天/手续费场景（标记待人工审核） |

## 隐私与安全

- **所有处理均在本地** — 不向外部服务器发送任何数据
- **input/ 和 output/ 目录已排除在 git 之外** — 财务数据不会离开你的电脑
- **样本测试数据已匿名化** — 仓库中不包含真实个人信息
- **导入前审核工作流** — 模糊匹配会报告待人工审核，而非静默丢弃

## 贡献指南

欢迎贡献！请随时提交 Pull Request。

1. Fork 本仓库
2. 创建功能分支（`git checkout -b feature/AmazingFeature`）
3. 提交变更（`git commit -m 'Add some AmazingFeature'`）
4. 推送分支（`git push origin feature/AmazingFeature`）
5. 发起 Pull Request

## 致谢

- [Beancount](https://github.com/beancount/beancount) by Martin Blais — 启发本项目的优秀纯文本复式记账系统
- [Beancount 文档](https://beancount.github.io/docs/) — 全面的文档与最佳实践
- Beancount 生态系统的所有贡献者

## 许可证

本项目采用 MIT 许可证 — 详见 [LICENSE](LICENSE) 文件。

## 免责声明

这是一个独立的第三方工具，与以下机构无官方关联、背书或联系：
- 支付宝或蚂蚁集团
- 微信支付或腾讯
- 本工具中提及的任何金融机构

本工具仅供教育和个人财务管理目的。作者不对基于本软件输出做出的任何财务决策负责。

## 相关链接

- [Beancount 官方仓库](https://github.com/beancount/beancount)
- [Beancount 文档](https://beancount.github.io/docs/)
- [外部贡献与工具](https://beancount.github.io/docs/external_contributions.html)
- [纯文本记账](https://plaintextaccounting.org/)
- [上游开源仓库](https://github.com/CacinieP/FinancialBeancount)
