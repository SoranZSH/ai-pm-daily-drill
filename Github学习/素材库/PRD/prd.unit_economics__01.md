---
card_id: PRD-unit_economics-01
concept: prd.unit_economics
source_type: C
source: Intercom Fin 官方定价页与帮助文档（URL 见「补充」）
credibility: 高
collected: 2026-11-01
use_for: [案例, X论据, 误区]
privacy: 无需
used_in: [PRD-X005]
---

## 论点（一句话）

AI 客服按「结果」而不是按席位或调用量计费，账单跟着交付的工作走，但「结果」的口径（尤其是默认解决）就成了买卖双方的合同条款。

## 原文摘录（最多 2 句，可省略）

- Resolution: "No further help is requested after the last AI answer."（帮助文档的结果类型表）
- "You will only be charged at most once per conversation, regardless of how many questions the customer asks or how many Procedures Fin runs in that conversation."

## 要点（自己的话，3–5 条）

- 价格（2026-11-01 核实）：Intercom 自带客服系统的版本标「From $0.99 per outcome」，另加每席位每月 19 美元；接入其他客服系统（Salesforce、HubSpot 等）的版本为每个结果 0.99 美元、每月最少 50 个结果，并注明「Minimum commitments apply」。
- 结果类型：解决、按配置流程办完再转人工或转工作流（Procedure handoff）、不合格线索判定、自助分流，各 0.99 美元；销售场景的合格线索判定（qualification）9.99 美元。
- 解决分两种：客户确认答案有帮助（确认解决），或客户没再求助就离开对话（默认解决）。
- 不计费与扣回：客户明确要求转人工不计费；识别到客户不满时默认触发不计费的升级；已算解决的对话，客户之后回到同一对话求助，这次解决会扣回（跨账期也扣）。
- 每个对话最多计一次费，不论客户问了多少问题、Fin 跑了多少个流程。

## 可用例子

- 面试里拿它说明按结果定价：买方可以直接把每次解决的费用和坐席处理一张工单的成本对比。
- 以下是推论，不是官网原文，使用时要说成自己的判断：每个对话最多计一次，长对话或最后转人工时多出的算力成本由厂商承担；默认解决可能把直接放弃的客户也算进去，所以需要配合复联率和满意度来校验。

## 易错点 / 常见误解

- 把它说成「每次解决 0.99 美元」：官网现在按「结果」计费，解决只是其中一类；销售场景的合格线索是 9.99 美元；Intercom 自带客服版本写的是「起价」。
- 说「转人工就不收费」：客户主动要求转人工不收费，但按配置流程办完再转人工（Procedure handoff）是计费结果。
- 把官网没有写的动机（例如「为了对齐双方激励」）说成 Intercom 的原话。帮助文档只写了 "You will never be charged for an outcome that didn't happen"。

## 英文表达（可选）

- outcome-based pricing；charged at most once per conversation；assumed resolution / confirmed resolution；the vendor absorbs the extra compute

## 补充

- 定价页：https://fin.ai/pricing （核实日期 2026-11-01）
- 帮助文档「Fin AI Agent outcomes」：https://www.intercom.com/help/en/articles/8205718-fin-ai-agent-outcomes （核实日期 2026-11-01）
- 审阅人另列了 https://www.intercom.com/pricing 和 https://www.intercom.com/help/en/articles/15599377-update-to-fin-performance-metrics （据审阅报告，2026 年 6–8 月改的是绩效指标，计费口径未变；本卡未单独打开核实）
- 价格和口径会调整，用之前重新打开定价页核对。
