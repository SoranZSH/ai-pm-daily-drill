# How it was built

[English](#english) · [中文](#中文)

---

## English

This project was built by one person acting as **product owner**, working with several AI coding agents. I didn't write most of the code by hand. My job was the one a PM has on any team: decide what to build and in what order, write requirements an engineer can execute, review the output, and own the trade-offs.

### Timeline

| Phase | What happened | My role |
|---|---|---|
| **1 · Rescue** | A vibe-coded "daily question" popup whose source and history I had lost. Located it, added a bank template and a one-click updater, and fixed the study counter so that only finished questions count. | Defined "what counts as studying"; designed the *swap → skip today* button to separate "boring question" from "lazy day" |
| **2 · Two programs, two contracts** | Split the system into a content side (Github学习) and a practice side (每日一题), connected only by a folder and two JSON formats. | Required loose coupling as a hard constraint |
| **3 · Spec before code** | Another model drafted a design spec. I had it reviewed for three things: gaps caused by missing history, broken coupling, and whether a small model could execute it. It was rewritten around permanent IDs, F/X levels and multilingual discovery. | Decided to replace the old 306-question bank; asked for foundation vs extension levels so advanced content never arrives first |
| **4 · Delegated milestones** | A smaller model (Haiku) implemented the collector milestone by milestone, with acceptance tests, a stop-after-each-milestone rule and an explicit "never do" list: never read my learning history, never write a token to disk, never call an LLM from the collector. A stronger model reviewed its progress. | Set the gates; added do-not-disturb (full screen, mic/camera) after realising a reminder could pop up mid-interview |
| **5 · Seeding the library** | A 90-day × 5 backfill collected 50 projects. The reviewer flagged 15 "off-topic" projects (scrapers, proxies, API relays, jailbreak prompts) and proposed filters. | **Overruled the filter**: these are AI "sensors" and security cases, and filtering belongs at question-writing time. The filter code was reverted and the decision written into the spec |
| **6 · Answer review redesign + spec v2.1** | Redesigned the answer screen into *check first, understand second*. Wrote the field spec, a fully worked example, staged authoring prompts and an independent-review prompt. A third model (Gemini) wrote the questions. | Chose "suggest, don't auto-grade" for the self-check |
| **7 · Catching process failures** | Gemini split the *planning* step into 10 parallel sub-tasks, so no single view checked cross-domain duplicates or prerequisites. I also noticed the prompts never used the collected library at all. | Stopped the run and **restarted from scratch** rather than patching a plan built on missing inputs |
| **8 · Review loop** | Review of the first domain found a wrong compounding-probability example (0.9¹⁰ ≈ 35%, not "0 → 1"), overclaims, and temporary IDs leaking into answer text. The updater gained a check so that last one can't recur. | Approved fix-then-import |
| **9 · Operations** | Logs showed the daemon had been silent for 8 days while the collector kept running. Root cause was narrowed to a Win32 call that can block forever, plus no restart path. Fixed with a non-blocking API, an in-process watchdog and a scheduled relaunch task. | Asked for a health check; accepted the reliability changes |
| **10 · Beyond AI topics** | Extended the bank to general B2B/SaaS PM skills (requirements, business architecture, information systems), scoped to my target roles. | Trimmed overly niche topics; kept the bank aligned to my job search |

### What I learned about working with AI agents

1. **Separate judgment from execution.** Setting goals, finding the key difficulty, choosing between options and reviewing are judgment work: I kept them, or gave them to the strongest model. Inventorying, generating candidates and filling in a skeleton are execution: those were safe to delegate. The one time planning was parallelised, quality dropped.
2. **The writer should not be the reviewer.** Every batch of questions was reviewed in a fresh conversation, ideally by a different model, with an explicit "find the single most damaging problem" step.
3. **Move checks into tools.** Anything a reviewer catches twice becomes a rule in the updater: aligned sentences must join into the answer, quoted phrases must appear verbatim, no temporary IDs in text.
4. **Write the owner's decisions down.** "Keep off-topic projects" and "suggest, don't auto-grade" are recorded in the spec, so the next agent doesn't helpfully undo them.
5. **Restart beats patching** when the input to a plan was wrong.
6. **Read the logs.** The worst bug, an 8-day silent outage, had no error message. It showed up only as a gap in the log.

### Where to look

| Evidence | File |
|---|---|
| Full design spec (milestones M0–M6, acceptance cases) | [`Github学习/AI实践采集与题库生成_方案设计.md`](../Github学习/AI实践采集与题库生成_方案设计.md) |
| Question spec v2.1 with worked example | [`Github学习/题库模板/题库编写规范.md`](../Github学习/题库模板/题库编写规范.md) |
| Staged authoring and independent-review prompts | [`Github学习/题库模板/`](../Github学习/题库模板/) |
| Decision record before the collector build | [`Github学习/开发记录/协助决策_M3开工前状态.md`](../Github学习/开发记录/协助决策_M3开工前状态.md) |
| Review reports and self-check reports | [`Github学习/开发记录/`](../Github学习/开发记录/) |

---

## 中文

这个项目由一个人以**产品负责人**的身份，和多个 AI 编程助手协作完成。大部分代码不是我手写的。我做的是产品经理在任何团队里都要做的事：决定做什么、先做什么，写出工程师能执行的需求，审查产出，并为取舍负责。

### 时间线

| 阶段 | 发生了什么 | 我的角色 |
|---|---|---|
| **1 · 抢救** | 一个 vibe coding 做出来的每日一题弹窗，源码和对话记录都找不到了。找回目录，补上题库模板和一键更新工具，并修正学习计数，改成只有真正练完才算一天 | 定义「什么才算学习」；设计「随机换题 → 算了，今天休息」，用来区分「题目没吸引力」和「今天犯懒」 |
| **2 · 两个程序、两份契约** | 拆成出题侧（Github学习）和练题侧（每日一题），两边只通过一个文件夹和两种 JSON 格式相连 | 把松耦合定为硬约束 |
| **3 · 先有方案、再写代码** | 另一个模型起草了设计方案。我让它接受三项审查：有没有因不了解历史造成的漏洞，有没有破坏耦合，小模型能不能照着执行。随后围绕永久题号、F/X 分层、多语言发现重写 | 决定替换旧的 306 道题；要求区分基础与拓展，确保拓展内容不会先于基础出现 |
| **4 · 按里程碑委派** | 较小的模型（Haiku）逐个里程碑实现采集程序：每个里程碑带验收用例，做完必须停下等确认，另有明确的禁止清单（不得读取我的学习记录、不得把 Token 写进文件、采集程序不得调用大模型）。由更强的模型复查进度 | 设置关卡；意识到提醒可能在面试中弹出后，加上勿扰检测（全屏、麦克风 / 摄像头） |
| **5 · 初始化资料库** | 回溯 90 天、按 5 倍规模收录了 50 个项目。审阅方指出其中 15 个「跑题」项目（爬虫、代理、API 中转、越狱提示词），并提出过滤方案 | **否决过滤**：这些是 AI 的「传感器」和安全案例，筛选应该放在出题环节。过滤代码随即撤回，决定写进方案 |
| **6 · 解析页重设计 + 规范 v2.1** | 把解析页改成「先核对、后讲透」。写字段规范、完整示范题、分阶段出题提示词和独立审题提示词。由第三个模型（Gemini）出题 | 决定要点自查「只给建议、不自动评分」 |
| **7 · 发现流程问题** | Gemini 把规划拆成 10 个并行子任务，没有一个全局视角去检查跨领域重复和前置关系。我还发现提示词完全没用上采集来的资料库 | 叫停并**从头重来**，不在缺了输入的规划上修补 |
| **8 · 审题闭环** | 第一个领域的审阅发现：复合概率例子算错（0.9¹⁰ ≈ 35%，不是「从 0 到 1」）、说法过头、临时编号混进正文。更新工具随即加了检查，防止最后这类问题再次出现 | 批准「改后导入」 |
| **9 · 运维** | 日志显示采集程序照常运行，后台提醒却静默了 8 天。原因收敛到一个可能永久阻塞的 Win32 调用，加上没有任何重启机制。修复为不阻塞的接口、程序内看门狗和定时拉起任务 | 要求做健康检查；接受可靠性改造 |
| **10 · 扩展到 AI 以外** | 题库扩展到 B2B / SaaS 产品经理的通用能力（需求分析、业务架构、信息系统），范围对准我的目标岗位 | 删去过于小众的主题，让题库服务于求职方向 |

### 和 AI 助手协作的体会

1. **判断与执行分开。** 定目标、找关键难点、在方案之间取舍、审阅都是判断，由我来做，或交给最强的模型；盘点、生成候选、往骨架里填内容是执行，可以放心委派。唯一一次把规划并行化，质量就掉了。
2. **写的人不审自己。** 每批题目都在新对话里审，最好换一个模型，并且有「找出最致命的一个问题」这一步。
3. **把检查搬进工具。** 审阅者抓到两次的问题，就变成更新工具里的规则：逐句对照必须拼得回答案，摘录必须原样出现，正文里不能有临时编号。
4. **把负责人的决定写下来。** 「保留跑题项目」「只建议、不自动评分」都记在方案里，免得下一个助手好心把它们改回去。
5. **规划的输入错了，重来比修补划算。**
6. **要读日志。** 最严重的故障（8 天静默停机）没有任何报错，只表现为日志里的一段空白。

### 证据在哪里

| 内容 | 文件 |
|---|---|
| 完整设计方案（里程碑 M0–M6、验收用例） | [`Github学习/AI实践采集与题库生成_方案设计.md`](../Github学习/AI实践采集与题库生成_方案设计.md) |
| 题库编写规范 v2.1 与示范题 | [`Github学习/题库模板/题库编写规范.md`](../Github学习/题库模板/题库编写规范.md) |
| 分阶段出题提示词与独立审题提示词 | [`Github学习/题库模板/`](../Github学习/题库模板/) |
| 采集程序开工前的决策记录 | [`Github学习/开发记录/协助决策_M3开工前状态.md`](../Github学习/开发记录/协助决策_M3开工前状态.md) |
| 审阅报告与自检报告 | [`Github学习/开发记录/`](../Github学习/开发记录/) |
