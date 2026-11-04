---
card_id: STR-pricing-01
concept: str.pricing
source_type: C
source: GitLab Handbook「Pricing model」https://handbook.gitlab.com/handbook/company/pricing/ ；GitLab Docs「Issue boards」https://docs.gitlab.com/user/project/issue_board/ ；GitLab 定价页 https://about.gitlab.com/pricing/
credibility: 高
collected: 2026-11-01
use_for: [案例, X论据, 误区]
privacy: 无需
used_in: [STR-X004]
---

## 论点（一句话）

GitLab 采用「按买方分层的开源核心」：功能进哪一档，看谁最在意它、谁会为它拍板付钱，而不看谁在用它，也不按公司规模或使用范围收费。

## 原文摘录（最多 2 句，可省略）

- "we focus not on the user of the feature, but on the buyer"
- "Buyers make sense, since a higher-cost plan needs a higher-placed buyer."

## 要点（自己的话，3–5 条）

- 三档对应三类买方：Free 面向单个开发者（自己决定），Premium 面向团队（总监拍板），Ultimate 面向全组织的战略性使用（高管拍板）。分档标准是「Who cares most about the feature」。
- 放弃的方案及理由：按公司规模收费行不通，因为有些小公司也需要最高档的功能；为更多使用（采用范围）多收费，会抑制整个生命周期的使用。
- 两条护栏：开源功能不应挪进付费档；拿不准时默认放到更低一档。为了推动使用，可以违背买方原则，但只能往低档放；产品经理不应在没有后续付费计划时随意下放功能。
- 看板例子（手册写法）：项目和组看板免费（个人贡献者通常只需一个组看板）；跨组的多个组看板放 Premium（对应总监）；史诗泳道放 Ultimate（价值在高管看全公司项目组合）。
- 时效差异：现行产品文档把「按史诗分泳道」标为 Tier: Premium, Ultimate，免费版只能用一个组看板，多个组看板需 Premium 及以上。即手册例子已过时，泳道已下放，正好印证「拿不准往低档放」。

## 可用例子

- 合并请求：合并冲突解决放 Free（个人日常工作流）；合并审批放 Premium（总监要求指定人审批，虽然总监不是主要使用者）。
- 题目中可迁移到 B 端 SaaS：客服系统里坐席天天用的功能留低档，主管才在意的质检、报表、审计放高档。

## 易错点 / 常见误解

- 把「not on the user, but on the buyer」误写成「不看功能多高级」：手册对照的是买方与使用者，全页没有拿功能复杂度作对照。
- 背价格：手册表格仍列 Premium 29、Ultimate 99 美元/人/月，但官网现行定价页 Ultimate 为 custom pricing，手册自己也说以定价页为准。题目里不写价格。

## 英文表达（可选）

- who cares most about the feature
- a higher-cost plan needs a higher-placed buyer
- when in doubt, default to the lower tier

## 补充

- 核实日期：2026-11-01，三个 URL 均已打开逐条核对。
- 同一手册体系还有客户健康度页面（GRO 领域案例题使用），可互相引用。
