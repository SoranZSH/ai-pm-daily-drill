---
card_id: LCM-lifecycle-01
concept: lcm.lifecycle
source_type: C
source: Atlassian 官方公告与许可页（URL 见「补充」）
credibility: 高
collected: 2026-11-01
use_for: [案例, X论据, 误区]
privacy: 无需
used_in: [LCM-X004]
---

## 论点（一句话）

Atlassian 退出 Server 版是 B 端版本分阶段下线的典型：先停售、再停支持，中间留约三年并补贴迁移；但自管的 Data Center 按大团队定价，小客户实际只能上云，而 Data Center 本身也已宣布在 2029 年终止。

## 原文摘录（最多 2 句，可省略）

- "we will offer three years of support and maintenance for your server products"（journey-to-cloud 公告）
- "End of life for impacted Data Center products will take place on March 28, 2029 at 23:59 PST."（Data Center end-of-life 页）

## 要点（自己的话，3–5 条）

1. 时间线（PT）：2020-10-16 宣布；2021-02-02 停售新的 Server 许可；2022-02-15 停止用户档位升降；2023-02-15 停售新的 Server 插件（含免费插件）；2024-02-15 终止支持和缺陷修复，续费按终止日折算。
2. 官方理由：更加聚焦，做「云优先」公司；公告也说部分客户的业务要求可能使他们永远无法上云，因此保留自管的 Data Center。
3. 迁移配套：Atlassian Migration Program（免费迁移工具、专门迁移支持团队）、按剩余维护期最长 12 个月的免费云迁移试用、对符合条件客户的忠诚折扣。Server 终止支持页写明 Cloud 是「推荐给大多数客户」的选项。
4. 门槛争议：官方 Data Center 价格表中，Jira Data Center 最低一档 500 用户（年费 51,000 美元，2026-02-17 起 59,000 美元），Confluence Data Center 最低 500 用户，Jira Service Management Data Center 最低 50 用户。小团队实际上难以选择自管路线。
5. 后续：2025-09-08 宣布 Data Center 下线。2026-03-30 起不再向新客户销售；2028-03-30 起老客户不能再买新订阅；2029-03-28 终止。Bitbucket 和 Bamboo 的 Data Center 不在此列。受监管客户可选 Government Cloud（FedRAMP Moderate）和 Isolated Cloud，个别客户可例外延长维护。

## 可用例子

- 「停售」与「停支持」分开：让客户在失去任何东西之前三年就看到变化。
- 「纸面两条路，实际一条路」：路径数量不等于每类客户都有负担得起的去处。

## 易错点 / 常见误解

- 把 Data Center 讲成不能上云客户的长期归宿：2025 年它也宣布下线。
- 说成「所有客户都有两个选择」：Jira Data Center 从 500 用户起售，小客户实际只能上云。
- 「超过九成客户从云开始」指新客户的起点，不是现有 Server 客户的迁移比例，不要混用。

## 英文表达（可选）

- retire a version in stages rather than flipping a switch
- on paper there were two paths
- renewals were prorated to the end date

## 补充

来源（均于 2026-11-01 核实）：
- https://www.atlassian.com/blog/announcements/journey-to-cloud
- https://www.atlassian.com/licensing/server-end-of-support
- https://www.atlassian.com/blog/it-teams/new-server-app-sales-ending-february-15
- https://www.atlassian.com/licensing/future-list-pricing/data-center-pricing/pricing-tables
- https://www.atlassian.com/blog/company-news/atlassian-ascend
- https://www.atlassian.com/licensing/data-center-end-of-life

对应题目：LCM 案例题「Atlassian 停售 Server 版：B 端版本该怎么下线？」（导入后回写正式题号）。
