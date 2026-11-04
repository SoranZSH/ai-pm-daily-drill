---
card_id: GRO-customer_success-01
concept: gro.customer_success
source_type: C
source: GitLab Handbook · Customer Health Scoring · https://handbook.gitlab.com/handbook/customer-experience/customer-health-scoring/ （旧路径 /handbook/customer-success/customer-health-scoring/ 会自动跳转；页面显示最后修改 2026-09-24）
credibility: 高
collected: 2026-11-01
use_for: [案例, X论据, 误区]
privacy: 无需
used_in: [GRO-X004]
---

## 论点（一句话）

健康度评分要能讲清「为什么变红」：分组加权、保留客户成功经理的判断、把缺失数据当未知，才能指向下一步行动。

## 原文摘录（最多 2 句，可省略）

- "When the CSM Sentiment score becomes red, the overall score will automatically become red."
- "If usage data stops being received into Gainsight, the health measures will move to 'NA' after 60 days."

## 要点（自己的话，3–5 条）

1. 五组加权，GitLab 称为 PROVE：产品（Product）50%，含许可证激活、用户活跃、用例采用；风险（Risk）25%，含 CSM 判断和续约商机风险；成果（Outcomes）10%；客户之声（VoC）5%；互动（Engagement）10%。
2. 在 Gainsight 中计分：绿 75–100，黄 50–74，红 0–49。CSM 判断为红时整体自动变红，恢复后再按常规权重计算。
3. 缺失的指标记为 NULL，不当作红，权重重新分给其他指标。新客户上手的前 30 天，除 CSM 判断外的指标通常为 NULL。
4. 处理过期数据：使用数据停止上报 60 天后改为 NA；CSM 判断 90 天未更新标为过期，120 天后设为 NA；客服类指标 30 天未更新设为 NA。
5. 产品使用按客户所购版本的功能来评。手册说第一版是多指标合成的「黑箱」，使用者看不懂，也不能指导行动。

## 可用例子

- 许可证激活看的是席位「是否已分配」；是否真在用，另看月活用户占计费用户的比例。
- 席位扩展信号：许可证使用率约 90%、活跃用户占比超过 80%。缩减信号：许可证使用率低于 75%（不含上手期客户）。

## 易错点 / 常见误解

- 把缺数据当成差，会制造大量假警报。手册的做法是记 NULL 或 NA，不当作红。
- 「风险组以 CSM 判断为主」是推断。原文只写了 CSM Sentiment 加续约商机风险，共占 25%。
- 「60 天后清空」不准确，原文是改为 NA。

## 英文表达（可选）

- built to be explained, not just calculated
- treat missing data as unknown, not bad

## 补充

- 手册另有两个预测模型：Propensity To Expand、Propensity To Churn or Contract。题里没有用到。
- 可与 STR 领域「以 GitLab 为例：开源核心产品如何按买方分层定价」互相引用。
