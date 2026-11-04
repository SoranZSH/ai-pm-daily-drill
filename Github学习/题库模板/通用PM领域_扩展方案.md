# 产品通用轨 · 扩展方案与补充提纲（v2.2 修订版）

> 2026-10-31 修订：以 NPDP（PDMA 知识体系第 3 版，7 章）作为覆盖检查清单，按「B 端自研 / SaaS 产品经理 + 个人小型 C 端项目」的方向做了裁剪。
> 配套文档：`知识搜集方案.md`、`碎片内容整合规则.md`、`出题提示词_通用PM.md`、`../知识地图_通用PM扩展草案.json`。

## 一、能不能直接加？——可以，不需要改代码

| 组件 | 怎么处理领域 | 加新领域要改吗 |
|---|---|---|
| `题库更新.exe` | 领域由更新文件声明（file、domain、概念键前缀），没有写死的领域清单 | 不用改，已在沙盒实测新建 REQ 分类导入成功 |
| 每日一题主程序 | 读取 `当前题库\` 全部文件，选题只看层级、前置、导入日期 | 不用改 |
| 采集程序 | 只收 GitHub 热门 AI 项目；用知识地图别名给项目打标签 | 不用改，但别名有误匹配缺陷，见工程需求第 1 条 |

## 二、定位与裁剪原则

**目标读者**：方向是 B 端自研或 SaaS 产品经理，也会自己做小型 C 端项目；缺少程序员底层基础。

**一个概念进入产品通用轨，必须同时满足三条：**

1. **行业中立**：换三个以上行业仍然成立；不依赖实体制造知识，也不依赖某个行业的监管细则（硬件、支付、电商履约、游戏数值、医疗合规等一律不收）。
2. **对方向有用**：在 B 端 / SaaS 产品经理的日常工作或面试中会真正用到，或者能直接用在个人小项目上。
3. **讲得出 60–90 秒的通用答案**：属于研究方法学、学术理论细节、只适合专门岗位（用户研究员、项目管理专员、战略咨询）的内容不单列，最多作为其他概念里的一句话。

过不了这三条的内容，只能在案例题里当例子，不单独出题。

## 三、领域划分（产品通用轨 11–19）

| 文件 | 分类 category | category_en | domain | 前缀 | 概念数 | 批次 |
|---|---|---|---|---|---|---|
| 11_requirements.json | 需求分析与管理 | Requirements Analysis & Management | REQ | `req.` | 9 | 第一批 |
| 12_business_arch.json | 业务架构与流程 | Business Architecture & Process | BIZ | `biz.` | 10 | 第一批 |
| 13_info_systems.json | 信息系统与技术基础 | Information Systems & Tech Literacy | SYS | `sys.` | 11 | 第一批 |
| 14_data_metrics.json | 数据分析与指标体系 | Data, Metrics & Experimentation | DAT | `dat.` | 8 | 第二批 |
| 15_growth_cs.json | 增长与客户成功 | Growth & Customer Success | GRO | `gro.` | 8 | 第二批 |
| 16_product_strategy.json | 产品战略与商业模式 | Product Strategy & Business Model | STR | `str.` | 10 | 第二批 |
| 17_product_design.json | 用户研究与产品设计 | User Research & Product Design | UXD | `uxd.` | 6 | 第三批 |
| 18_delivery.json | 开发流程与团队协作 | Delivery Process & Collaboration | DLV | `dlv.` | 9 | 第三批 |
| 19_lifecycle.json | 产品立项与生命周期 | Product Investment & Lifecycle | LCM | `lcm.` | 5 | 第三批 |

共 9 个领域、76 个概念。

**批次理由**：
- 第一批是你点名的三块，也是 B 端面试里的硬功夫。
- 第二批是 SaaS 的生意逻辑：指标、留存与客户成功、定价与商业模式。
- 第三批里，设计、交付和立项你已经有实际经验，补成体系化表达就行。

## 四、NPDP 覆盖对照

NPDP 讲「产品创新管理」，面向各种行业；本轨道讲「数字产品经理怎么干活」。两者的对应关系如下：

| NPDP 章节 | 本轨道承接 | 主动不收的部分 |
|---|---|---|
| 第 1 章 产品创新管理（生命周期、财务分析、指标） | LCM 全部；DAT 指标体系 | 需求预测（制造业备货逻辑） |
| 第 2 章 战略 | STR：战略分解、创新类型、平台生态、定位、商业模式 | 知识产权战略、技术 S 曲线 |
| 第 3 章 组合管理 | LCM：产品组合与资源分配 | 组合管理的评分模型细节 |
| 第 4 章 产品创新流程 | DLV：敏捷、混合交付、立项与阶段评审（门径管理 / IPD）；STR：精益创业 | 并行工程 |
| 第 5 章 设计与开发工具 | UXD：原型、可用性、设计系统；REQ：Kano | 创意方法、设计思维流程、实体设计、制造装配、可持续设计、FMEA |
| 第 6 章 市场调研 | UXD：用户研究方法；REQ：需求获取；DAT：A/B 实验；GRO：客户反馈闭环 | 民族志、焦点小组、联合分析、试销 |
| 第 7 章 文化、团队与领导力 | DLV：产品经理的角色与无职权影响力、干系人管理 | 创新文化、团队结构分类 |

NPDP 没有、但本轨道必须有的：**业务架构（BIZ）、信息系统（SYS）、数据埋点与数仓（DAT）、SaaS 指标与客户成功（GRO）**。这几块是 B 端与 SaaS 方向和传统产品创新最大的差别。

## 五、裁剪记录

### 5.1 你点到的几项

| 内容 | 它讲什么 | 处理 | 理由 |
|---|---|---|---|
| 民族志 | 研究者长时间进入用户的真实生活或工作环境，像人类学家一样观察记录 | **删除独立概念**；轻量版「现场观察 / 跟岗」并入需求获取方法 | B 端真正用得上的是到客户现场看一天他们怎么干活，这件事一句话就能讲清，不需要方法学 |
| 焦点小组 | 请 6–10 名消费者坐在一起，由主持人引导讨论 | **删除**；在用户研究方法里提一句 | 主要用于消费品营销；B 端客户少、决策链长，几乎不用 |
| 联合分析 | 让用户在多组「功能 + 价格」组合中做选择，用统计模型算出每项属性值多少钱 | **删除**；定价题里最多提一句 | 需要专门的统计设计，属于定价研究员的工作 |
| 创意方法 | 头脑风暴、SCAMPER（替代、合并、改造等七个提问方向）、TRIZ（源自专利研究的发明原理） | **删除** | 偏工业设计与创新工作坊，面试和日常工作都很少用 |
| 设计思维 | 「共情—定义—构思—原型—测试」五步流程 | **删除独立概念** | 核心环节已经由用户研究、原型、可用性测试覆盖，单讲流程容易沦为口号 |
| 创新文化 | 组织怎样容忍试错、鼓励创新 | **删除** | 管理层话题，求职阶段和个人项目都用不上 |
| 团队结构分类 | 职能型、轻量级、重量级、自治型团队 | **删除**；换成「产品经理的角色与无职权影响力」 | 分类本身是 NPDP 考点，实际工作需要的是怎么推动不归你管的研发、设计、销售 |

### 5.2 其他一并裁剪或合并的

| 内容 | 处理 |
|---|---|
| 问卷与抽样 | 并入用户研究（定性与定量的选择、样本偏差） |
| 概念测试、概念开发 | 并入精益创业：原型验证、假门测试、最小可行产品 |
| 内测与试销 | 改为 B 端说法「试点与 POC」，并入上市策略 |
| 客户之声 | 改为「客户反馈闭环」（满意度、净推荐值、工单与销售反馈回流到路线图），放进增长与客户成功 |
| 服务蓝图 | 并入用户旅程，作为旅程地图在 B 端服务流程上的延伸 |
| 门径管理 | 与 IPD 合成一个概念「立项与阶段评审」（国内 B 端公司常用的 IPD 评审点就是它的变体） |
| 并行工程、知识产权、技术 S 曲线、需求预测、可持续设计、FMEA | 删除 |
| 战略层级 + OKR | 合成「战略分解与目标对齐」 |
| 归因分析 | 从数据领域移到增长领域，改为「获客渠道与归因」 |
| 企业级产品体验 | 并入原型与交互，作为 B 端视角，不单列 |
| 上线后落地推广 | 改为「客户实施与上线」，移到增长与客户成功 |

### 5.3 为方向新增的

| 新增概念 | 理由 |
|---|---|
| `sys.configurability` 标准化与定制化 | 「客户要个性化功能怎么办」是 SaaS 产品经理的头号面试题 |
| `gro.saas_metrics` SaaS 核心指标 | ARR、NRR、CAC、LTV 是看懂 SaaS 生意的门槛 |
| `gro.customer_success` 客户成功与健康度 | SaaS 靠续约赚钱；也正好接得上你在客户服务平台做流失项目的经历 |
| `str.platform_ecosystem` 平台化与开放生态 | 大型 B 端平台都走 PaaS、应用市场、开放接口的路线 |
| `str.lean_startup` 精益创业与最小可行产品 | 个人小项目最直接用得上的方法 |
| `lcm.gtm` 上市策略（产品驱动与销售驱动） | SaaS 是靠产品自己拉新（PLG），还是靠销售团队（SLG），决定了产品形态 |

## 六、与 AI 轨的边界

| 容易重叠的主题 | 归属 | 另一边怎么处理 |
|---|---|---|
| A/B 实验的统计原理 | `dat.ab_testing` | `evl.online_ab` 只讲模型版本对比等 AI 特有部分，以前者为前置 |
| 通用指标体系 | `dat.metric_system` | `prd.ai_metrics` 只讲采纳率、幻觉率等 AI 指标 |
| SaaS 定价、商业模式 | `str.pricing`、`str.business_model` | `prd.unit_economics` 只讲按 Token 计费带来的成本结构 |
| 自研还是采购 | `prd.build_vs_buy`（AI 轨） | 通用轨不单出；立项论证题需要时引用它 |
| 人工审批、流程中的人 | `biz.process_modeling` | `prd.human_in_loop` 只讲 AI 输出的人机协同 |
| 权限与隐私 | 系统实现归 `sys.auth`；合规归 `saf.privacy` | 互为前置 |
| 留存、流失 | `gro.retention_churn` | AI 轨不单出 |

## 七、补充提纲

题目为规划草稿，`q_cn` 已控制在 34 字内；正式规划时按 `出题提示词_通用PM.md` 第一步定稿。「NPDP」列标注对应章节，「–」表示 NPDP 不涉及。

### 11 需求分析与管理（REQ）· 第一批

学习目标：把一句模糊的业务诉求，变成分层、可排序、可验收的需求说明。

| 概念键 | 名称 | 一句话要点 | NPDP |
|---|---|---|---|
| req.requirement_levels | 需求层次 | 业务需求 → 用户需求 → 功能需求 / 非功能需求，层层可追溯 | – |
| req.real_need | 真实需求挖掘 | 区分用户提的方案和背后的问题（待办任务、5 Whys） | 6 |
| req.elicitation | 需求获取方法 | 访谈、现场观察 / 跟岗、工作坊、数据分析的适用场景 | 6 |
| req.user_story | 用户故事与验收标准 | 「作为…我想…以便…」+ INVEST + Given-When-Then | – |
| req.use_case | 用例与场景建模 | 用参与者、主流程、异常流程划定系统边界 | – |
| req.nfr | 非功能需求 | 性能、可用性、安全、合规；最易遗漏、上线后最致命 | – |
| req.prioritization | 需求优先级 | MoSCoW、RICE、Kano 分别解决必须性、性价比、满意度 | 5 |
| req.prd | 需求文档（PRD） | 背景目标、范围、流程、规则、原型、指标、验收 | – |
| req.change_control | 需求变更与范围控制 | 基线、影响评估、变更评审、需求追溯 | – |

| # | 层级 | 题型 | 建议题目 | 概念 | 前置 |
|---|---|---|---|---|---|
| 1 | F | knowledge | 需求分哪几层？业务需求、用户需求和功能需求有何区别？ | req.requirement_levels | – |
| 2 | F | knowledge | 用户说「我要一个导出按钮」，怎么找到他真正的需求？ | req.real_need | 1 |
| 3 | F | knowledge | 需求调研有哪些方法？访谈和现场跟岗各适合什么场景？ | req.elicitation | 1 |
| 4 | F | knowledge | 什么是用户故事？好的验收标准长什么样？ | req.user_story | 1 |
| 5 | F | knowledge | 用例怎样描述系统边界？主流程和异常流程为何都要写？ | req.use_case | 1 |
| 6 | F | knowledge | 什么是非功能需求？为什么它常被漏掉又最致命？ | req.nfr | 1 |
| 7 | F | knowledge | MoSCoW、RICE 和 Kano 各解决什么排序问题？ | req.prioritization | 1 |
| 8 | F | knowledge | 一份合格的 PRD 应该包含哪些部分？ | req.prd | 4, 5, 6 |
| 9 | X | method | 需求频繁变更时，如何控制范围又不失去业务方信任？ | req.change_control | 7, 8 |
| 10 | X | idea | B 端产品为什么不能「客户要什么就做什么」？ | req.real_need, req.prioritization | 2, 7 |
| 11 | X | method | 如何把「用 AI 提效」这种模糊需求拆成可验收的需求？ | req.user_story, req.nfr | 4, 6, LLM-F008 |
| 12 | X | case | 以一个开源工单系统为例：从调研到 PRD 怎么做？ | req.elicitation, req.prd | 3, 8 |

### 12 业务架构与流程（BIZ）· 第一批

学习目标：画出一家企业「靠什么能力、经过哪些流程、处理哪些业务对象」，找到适合数字化或 AI 介入的环节。

| 概念键 | 名称 | 一句话要点 | NPDP |
|---|---|---|---|
| biz.business_architecture | 业务架构总览 | 业务、应用、数据、技术四层架构的关系 | – |
| biz.capability_map | 业务能力地图 | 企业「能做什么」，比组织架构图更稳定 | – |
| biz.value_stream | 价值流 | 从客户触发到交付价值的端到端阶段，用来找瓶颈 | – |
| biz.process_modeling | 业务流程建模 | 泳道图、BPMN；角色、活动、网关、事件 | – |
| biz.domain_model | 领域模型与业务对象 | 实体、属性、关系；统一业务语言 | – |
| biz.state_machine | 业务状态机 | 订单、工单的状态与流转条件 | – |
| biz.business_rules | 业务规则 | 规则与流程分离；何时用规则引擎 | – |
| biz.org_permission | 组织、角色与审批 | 组织树、岗位、审批流的业务设计 | – |
| biz.as_is_to_be | 现状与目标流程 | As-Is 诊断、To-Be 设计、流程再造 | – |
| biz.b2b_vs_b2c | B 端与 C 端差异 | 决策链、使用者与购买者分离、流程驱动 | – |

| # | 层级 | 题型 | 建议题目 | 概念 | 前置 |
|---|---|---|---|---|---|
| 1 | F | knowledge | 什么是业务架构？它和应用、数据、技术架构什么关系？ | biz.business_architecture | – |
| 2 | F | knowledge | 什么是业务能力地图？为什么比组织架构图更稳定？ | biz.capability_map | 1 |
| 3 | F | knowledge | 泳道图和 BPMN 如何画清一个跨部门流程？ | biz.process_modeling | 1 |
| 4 | F | knowledge | 什么是领域模型？业务对象和关系怎么梳理？ | biz.domain_model | 1 |
| 5 | F | knowledge | 订单、工单为什么都需要状态机？状态流转怎么设计？ | biz.state_machine | 3, 4 |
| 6 | F | knowledge | 业务规则该写死在代码里，还是交给规则引擎？ | biz.business_rules | 3 |
| 7 | F | knowledge | As-Is 和 To-Be 流程分析分别要回答什么？ | biz.as_is_to_be | 3 |
| 8 | F | knowledge | B 端产品和 C 端产品在需求与设计上有何本质不同？ | biz.b2b_vs_b2c | 1 |
| 9 | X | method | 如何用价值流找到流程瓶颈，并判断哪里适合引入 AI？ | biz.value_stream, biz.as_is_to_be | 7, AGT-F001 |
| 10 | X | idea | 为什么把线下流程搬到线上，不等于数字化转型？ | biz.as_is_to_be, biz.capability_map | 2, 7 |
| 11 | X | method | 如何梳理一家企业的组织、角色与审批体系？ | biz.org_permission | 3, 4 |
| 12 | X | case | 以 ITSM 平台为例：工单流程如何承载企业业务架构？ | biz.process_modeling, biz.state_machine | 3, 5 |

### 13 信息系统与技术基础（SYS）· 第一批

学习目标：不写代码，但能读懂架构图和接口文档，能和研发讨论集成方案、部署形态、权限和配置化设计。

| 概念键 | 名称 | 一句话要点 | NPDP |
|---|---|---|---|
| sys.client_server | 前后端与客户端-服务器 | 浏览器 / App、后端服务、数据库各管什么 | – |
| sys.api | 接口（API） | 请求与响应、REST、状态码、接口文档怎么读 | – |
| sys.database | 数据库基础 | 表、字段、主键、关联；SQL 能做什么 | – |
| sys.enterprise_apps | 企业信息系统版图 | ERP、CRM、HRM、ITSM、OA 各管哪段业务（只讲版图，不深入某类系统设计） | – |
| sys.integration | 系统集成方式 | 接口直连、消息队列、批量同步、Webhook、集成平台 | – |
| sys.deployment | 部署形态 | SaaS、私有化、混合云、多租户 | – |
| sys.configurability | 标准化与定制化 | 配置项、元数据驱动、扩展点、二次开发的边界 | – |
| sys.auth | 认证与权限 | 单点登录、OAuth、基于角色的权限（RBAC） | – |
| sys.architecture_diagram | 读懂系统架构图 | 分层看：用户、应用、服务、数据、外部系统 | – |
| sys.reliability | 可用性与性能基础 | SLA、99.9% 的含义、并发、容量、降级 | – |
| sys.workflow_lowcode | 工作流与低代码平台 | 用配置代替开发的边界与代价 | – |

| # | 层级 | 题型 | 建议题目 | 概念 | 前置 |
|---|---|---|---|---|---|
| 1 | F | knowledge | 前端、后端和数据库分别负责什么？ | sys.client_server | – |
| 2 | F | knowledge | 什么是 API？产品经理如何读懂一份接口文档？ | sys.api | 1 |
| 3 | F | knowledge | 关系型数据库的表、主键和关联是什么意思？ | sys.database | 1 |
| 4 | F | knowledge | ERP、CRM、ITSM 等企业系统各管哪一段业务？ | sys.enterprise_apps | – |
| 5 | F | knowledge | 系统之间怎么打通？接口、消息队列和数据同步有何区别？ | sys.integration | 2, 3 |
| 6 | F | knowledge | SaaS、私有化部署和多租户有什么区别？ | sys.deployment | 1 |
| 7 | F | knowledge | 单点登录和角色权限是怎么实现的？ | sys.auth | 2 |
| 8 | F | knowledge | 99.9% 可用性意味着什么？产品经理要关心哪些指标？ | sys.reliability | 1 |
| 9 | F | knowledge | 如何读懂一张系统架构图？ | sys.architecture_diagram | 1, 5 |
| 10 | X | method | 客户老系统没法改造，新系统该如何与它集成？ | sys.integration | 5, 9 |
| 11 | X | idea | 客户都要个性化功能，SaaS 产品如何守住标准化？ | sys.configurability, sys.workflow_lowcode | 6 |
| 12 | X | case | 以 n8n 为例：工作流平台如何把多个系统串起来？ | sys.workflow_lowcode, sys.integration | 2, 5 |

> 12 题的素材仓库 `n8n-io/n8n` 已在资料库中；写题前先读原文。

### 14 数据分析与指标体系（DAT）· 第二批

| 概念键 | 名称 | 一句话要点 | NPDP |
|---|---|---|---|
| dat.metric_system | 指标体系 | 北极星指标、指标拆解树、口径定义 | 1 |
| dat.tracking | 埋点与数据采集 | 事件、属性、埋点方案与验收 | – |
| dat.funnel_cohort | 漏斗与同期群分析 | 转化漏斗、按批次看留存曲线 | – |
| dat.ab_testing | A/B 实验基础 | 假设、分流、样本量、显著性、常见陷阱 | 6 |
| dat.data_warehouse | 数据仓库与分层 | 原始层、明细层、汇总层、应用层 | – |
| dat.master_data | 主数据与数据治理 | 统一编码、口径、责任人 | – |
| dat.data_quality | 数据质量 | 完整、准确、及时、一致 | – |
| dat.self_service_bi | 报表与自助分析 | 固定报表与自助分析的取舍 | – |

素材：旧题库「数据产品经理」「数据分析与统计」「数据进阶」三类。

### 15 增长与客户成功（GRO）· 第二批

| 概念键 | 名称 | 一句话要点 | NPDP |
|---|---|---|---|
| gro.growth_model | 增长模型 | AARRR 漏斗、增长回路；产品驱动增长的基本逻辑 | – |
| gro.acquisition | 获客渠道与归因 | 渠道组合、获客成本、首次 / 末次 / 多触点归因 | 6 |
| gro.activation | 激活与上手 | 「啊哈时刻」、新手引导、首周价值 | – |
| gro.retention_churn | 留存与流失 | 留存曲线、流失预警、挽回 | – |
| gro.saas_metrics | SaaS 核心指标 | ARR / MRR、净收入留存（NRR）、CAC、LTV、回本周期 | 1 |
| gro.customer_success | 客户成功与健康度 | 健康度评分、续约、增购、客户成功经理的角色 | – |
| gro.implementation | 客户实施与上线 | 实施计划、数据迁移、培训、避免「验收即弃用」 | – |
| gro.feedback_loop | 客户反馈闭环 | NPS、满意度、工单与销售反馈如何回流到路线图 | 6 |

### 16 产品战略与商业模式（STR）· 第二批

| 概念键 | 名称 | 一句话要点 | NPDP |
|---|---|---|---|
| str.strategy_alignment | 战略分解与目标对齐 | 公司战略 → 产品战略 → 路线图；OKR 与 KPI | 2 |
| str.market_sizing | 市场规模测算 | TAM / SAM / SOM，自上而下与自下而上 | 2 |
| str.competitor | 竞品分析 | 维度、矩阵、差异化 | 2 |
| str.positioning | 定位与价值主张 | 目标客户、核心价值、替代方案 | 2 |
| str.business_model | 商业模式 | 收入来源、成本结构、商业模式画布 | 2 |
| str.pricing | 定价策略 | 价值定价；按席位、按用量、分层套餐 | 2 |
| str.innovation_types | 创新类型与颠覆式创新 | 渐进式、突破式、颠覆式；AI 对存量 SaaS 的冲击 | 2 |
| str.platform_ecosystem | 平台化与开放生态 | PaaS、应用市场、开放接口、合作伙伴 | 2 |
| str.pmf | 产品市场匹配 | PMF 的信号与衡量 | 4 |
| str.lean_startup | 精益创业与最小可行产品 | 构建—衡量—学习；原型验证、假门测试 | 4 |

### 17 用户研究与产品设计（UXD）· 第三批

| 概念键 | 名称 | 一句话要点 | NPDP |
|---|---|---|---|
| uxd.user_research | 用户研究方法 | 定性与定量怎么选；访谈、问卷、可用性数据；样本偏差 | 6 |
| uxd.persona_journey | 用户画像与旅程 | 角色、场景、触点、痛点；B 端服务流程延伸为服务蓝图 | 5 |
| uxd.info_architecture | 信息架构 | 导航、分类、页面层级 | 5 |
| uxd.prototype | 交互与原型 | 低保真到高保真；B 端表单、批量操作、权限下的交互 | 5 |
| uxd.usability | 可用性测试 | 任务、观察、启发式评估 | 5 |
| uxd.design_system | 设计系统 | 组件库、规范、一致性 | 5 |

### 18 开发流程与团队协作（DLV）· 第三批

| 概念键 | 名称 | 一句话要点 | NPDP |
|---|---|---|---|
| dlv.agile_scrum | 敏捷与 Scrum | 迭代、站会、评审、回顾 | 4 |
| dlv.delivery_models | 瀑布、敏捷与混合交付 | 客户项目为何常用混合模式 | 4 |
| dlv.phase_gate | 立项与阶段评审 | 门径管理与 IPD 的评审点：何时做「继续 / 停止」决策 | 4 |
| dlv.estimation | 估算与排期 | 故事点、关键路径、缓冲 | 1 |
| dlv.release | 发布与灰度 | 灰度、回滚、功能开关 | 4 |
| dlv.roadmap | 产品路线图 | 主题路线图与承诺边界 | 2 |
| dlv.pm_role | 产品经理的角色与影响力 | 和研发、设计、销售、客户成功的分工；没有职权时怎么推动 | 7 |
| dlv.stakeholder | 干系人管理 | 权力—利益矩阵、沟通计划 | 7 |
| dlv.risk | 风险与问题管理 | 风险登记、升级机制 | 1 |

### 19 产品立项与生命周期（LCM）· 第三批

| 概念键 | 名称 | 一句话要点 | NPDP |
|---|---|---|---|
| lcm.business_case | 立项论证与投资回报 | 成本、收益、回收期、ROI；向管理层或客户论证价值 | 1 |
| lcm.portfolio | 产品组合与资源分配 | 多条产品线或多个项目之间怎么分人和钱 | 3 |
| lcm.gtm | 上市策略 | 产品驱动（PLG）与销售驱动（SLG）；试点与 POC | 1 |
| lcm.lifecycle | 生命周期与功能下线 | 导入、成长、成熟、衰退各阶段的重点；功能与版本下线 | 1 |
| lcm.post_launch_review | 上线后复盘 | 目标对比、归因、决定继续投入还是止损 | 1 |

## 八、实施顺序

1. 确认本方案（领域、编号、裁剪、批次）。
2. 把 `知识地图_通用PM扩展草案.json` 中第一批（或全部）概念追加进 `知识地图.json`。草案每个概念都标了 `npdp` 字段，用于以后检查覆盖情况；导入工具和采集程序会忽略这个字段。
3. 按《知识搜集方案》为第一批每个概念收齐素材卡。
4. 规划 → 写题 → 独立审题 → 导入，一次一个领域。
5. 导入后把正式题号回写到素材卡，用 `提交存档.bat` 存档。

工程配套见 `..\开发记录\工程需求_通用PM扩展配套.md`。
