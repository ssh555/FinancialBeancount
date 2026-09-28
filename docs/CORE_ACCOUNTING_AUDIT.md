# Core accounting audit batch

[English](CORE_ACCOUNTING_AUDIT.md) | [简体中文](CORE_ACCOUNTING_AUDIT.zh-CN.md)

Further visual work on the Android review surface is temporarily frozen. The following core work must be completed and verified before that batch resumes:

- A payment-platform refund and its bank refund credit represent one economic event. Safe automatic merging requires the same amount and date, timestamps within five seconds, refund semantics on both records, and no competing candidate.
- Transfers to external fund-sale platforms such as Tiantian Fund remain expenses under the user-selected accounting policy; fund dividends are income. Movements into bank-internal products which remain part of total balance, such as Zhaochaobao and Tiantianying, are not consumption expenses.
- Every positive income amount displays a `+`; refunds, ordinary income, transfers, and investments remain separate measures.
- Bank accounts verify every transition as `previous balance + current amount = current balance`. A broken transition requires review and must not silently count as precisely reconciled.
- WeChat Wallet and Alipay balance accounts remain accounts. Without a balance field they show as unanchored; forward or backward reconstruction requires a trusted data or manual balance snapshot. Credit limits are shown separately as liabilities or facilities.
- Import, restore, and export operations show progress and disable interfering actions until completion, failure, or cancellation.
- Device acceptance records both cold-entry and cached revisit latency. Any write, import, or restore invalidates read caches.

The current September 2026 full-ledger audit starts from gross expense `11,503.75`, which includes an incorrectly classified bank-internal fund purchase of `1,802.05`. The external Tiantian Fund transfer of `6,000.00` remains an expense. The provisional corrected figures are gross expense `9,701.70`, refunds `29.71`, and net expense `9,671.99`; a complete rebuild, refund merge, and balance-break review must confirm the final values.
