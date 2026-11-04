"""采集器命令行入口与主流程（方案 M3.2、M3.5；M4 多语言；M5 分类与学习模式）。

用法：
    python collect.py [--force] [--since YYYY-MM-DD] [--max N] [--dry-run] [--fixtures DIR] [--verbose]

退出码：0 成功或正常跳过；1 未预期错误（记 failed）；2 配置错误（如没有 GITHUB_TOKEN）；
        3 网络中断或重试后仍失败（partial，不出包、不推进水位线）；4 另一个实例正在运行。

流程要点：
- 只读 当前题库\\*.json 与 知识地图.json；只写 state.db、采集包\\、采集日志\\、collect.lock。
- 不读取每日一题的学习记录，不调用任何大模型。
- 水位线 last_success_until 只在出包成功后才推进，且只会前进不会回退（取原水位线与窗口终点的较晚者）。
- Star 快照写入 state.db 的 snapshots 表（只追加，不覆盖）。
- --dry-run 在 state.db 的临时副本上运行，真实数据库、采集包、水位线都不会改变。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # Github学习

import classify as cl  # noqa: E402
import discover as dc  # noqa: E402
import enrich as en  # noqa: E402
import github_api as ga  # noqa: E402
import langid  # noqa: E402
import library  # noqa: E402
import pack  # noqa: E402
import rank  # noqa: E402
import stars  # noqa: E402
import store as stmod  # noqa: E402

UTC = dt.timezone.utc
EXIT_OK, EXIT_UNEXPECTED, EXIT_CONFIG, EXIT_PARTIAL, EXIT_LOCKED = 0, 1, 2, 3, 4
LOCK_STALE_SECONDS = 2 * 3600
INIT_MIN_README = 1500               # 初始化：README 清洗后至少这么多字才收入资料库
RATE_RESERVE = 600                    # 核心剩余低于此值时 max_candidates 减半
SCREEN_TEXT_CHARS = 3000              # 初筛语言识别的文本长度上限（协助决策 9.9 第 3 条）
TOKEN_HELP = (
    "未设置环境变量 GITHUB_TOKEN。\n"
    "  临时设置（当前 PowerShell 窗口）：  $env:GITHUB_TOKEN = \"<你的 Token>\"\n"
    "  永久设置（之后新开的窗口生效）：    setx GITHUB_TOKEN \"<你的 Token>\""
)


def default_paths() -> dict:
    return {
        "state_db": os.path.join(ROOT, "state.db"),
        "out_dir": os.path.join(ROOT, "采集包"),
        "log_dir": os.path.join(ROOT, "采集日志"),
        "bank_dir": os.path.join(ROOT, "当前题库"),
        "concepts": os.path.join(ROOT, "知识地图.json"),
        "library": os.path.join(ROOT, "资料库"),
        "lock": os.path.join(HERE, "collect.lock"),
        "directions": os.path.join(HERE, "方向词表.json"),
        "config": os.path.join(HERE, "config.json"),
    }


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Options:
    paths: dict
    token: str | None
    transport: object | None = None         # None → 真实网络（RealTransport）
    clock: object = field(default=lambda: dt.datetime.now(UTC))
    sleep: object = time.sleep
    config: dict | None = None
    force: bool = False
    since: dt.date | None = None
    max_projects: int | None = None
    dry_run: bool = False
    verbose: bool = False
    init: bool = False              # 初始化：回溯 init_days 天，按 init_scale 倍规模收录（v1.4）
    init_days: int = 90
    init_scale: int = 5


class RunLog:
    """日志写入 采集日志\\YYYYMMDD.log。所有消息先脱敏，Token 不会写入。"""

    def __init__(self, log_dir: str, token: str | None, clock, verbose: bool):
        os.makedirs(log_dir, exist_ok=True)
        self.token = token
        self.clock = clock
        self.verbose = verbose
        self.path = os.path.join(log_dir, f"{clock().astimezone():%Y%m%d}.log")

    def __call__(self, level: str, msg: str) -> None:
        msg = ga.redact(msg, self.token)
        line = f"{self.clock().astimezone(UTC):%Y-%m-%d %H:%M:%S} {level} {msg}"
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if self.verbose:
            print(line)


# ---------------- 锁 ----------------

def acquire_lock(path: str) -> bool:
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < LOCK_STALE_SECONDS:
            return False
        # 超过 2 小时视为残留锁，覆盖
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"pid={os.getpid()}\ntime={dt.datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}\n")
    return True


def release_lock(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


# ---------------- 题库扫描与已出题标记 ----------------

def load_concepts(path: str, log) -> dict:
    """知识地图的概念表（只读）：概念键 → {name, domain, aliases}。"""
    if not os.path.exists(path):
        log("WARNING", f"知识地图不存在：{path}，概念别名与前置概念中文名将不可用")
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("concepts") or {}


def scan_bank(bank_dir: str, log) -> dict:
    """只读 当前题库\\*.json。旧版题库（无 level/concepts/domain）按方案兼容处理。"""
    covered: set[str] = set()
    source_repos: dict[str, str | None] = {}
    domain_counts: dict[str, dict[str, int]] = {}
    items: list[dict] = []
    if not os.path.isdir(bank_dir):
        log("WARNING", f"题库目录不存在：{bank_dir}")
        return {"covered": [], "source_repos": {}, "domain_counts": {}, "items": []}
    for name in sorted(os.listdir(bank_dir)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(bank_dir, name), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            log("WARNING", f"跳过无法读取的题库文件 {name}：{e}")
            continue
        domain = data.get("domain") or "未标注"
        for it in data.get("items", []) or []:
            for c in it.get("concepts") or []:
                covered.add(c)
            level = it.get("level") or "F"           # 旧题没有 level，按基础题计
            counts = domain_counts.setdefault(domain, {"F": 0, "X": 0})
            counts[level if level in ("F", "X") else "F"] += 1
            items.append({"id": it.get("id"), "level": level, "concepts": list(it.get("concepts") or []),
                          "q_cn": it.get("q_cn"), "source_repos": list(it.get("source_repos") or []),
                          "added": it.get("added")})
            for repo in it.get("source_repos") or []:
                prev = source_repos.get(repo)
                added = it.get("added")
                if prev is None or (added and added < prev):
                    source_repos[repo] = added
    return {"covered": sorted(covered), "source_repos": source_repos,
            "domain_counts": domain_counts, "items": items}


def _baseline_questioned(api: ga.GitHubAPI, st: stmod.Store, cfg: dict, directions: dict,
                         repo_id: int, full: str, meta: dict | None, log) -> None:
    """记录已出题仓库的基线（只在字段为空时写入）：方向（快速分类）与上次记录的 release。

    无 release 时记空字符串，表示「已查过，没有 release」，之后不再重复请求。
    """
    if meta is None:
        r = api.get(f"/repos/{full}")
        if r.status != 200 or not isinstance(r.body, dict):
            log("WARNING", f"已出题仓库 {full} 返回 {r.status}，无法记录基线")
            return
        meta = r.body
    rel = en.fetch_latest_release(api, full, cfg["release_max_chars"])
    cls = cl.classify(directions, meta.get("topics"), meta.get("name"), meta.get("description"), "")
    st.set_questioned_baseline(repo_id, cls["direction"], (rel or {}).get("tag") or "")


def mark_questioned(api: ga.GitHubAPI, st: stmod.Store, source_repos: dict, cfg: dict,
                    directions: dict, now: dt.datetime, log) -> None:
    """把题库 source_repos 中的仓库标为 questioned，并记录方向与 release 基线。

    先查本地 repos 表（按 full_name，不区分大小写）；查到则直接标记，不调用 API（基线缺失时才补查）；
    查不到才通过 API 解析 repo_id（方案 M3 第 9.7 节 (c)）。
    """
    for full, added in sorted(source_repos.items()):
        row = st.repo_by_full_name(full)
        if row:
            if row["status"] != "questioned":
                st.set_repo_status(row["repo_id"], "questioned", None, added)
            if row["direction"] is None or row["last_release_tag"] is None:
                _baseline_questioned(api, st, cfg, directions, row["repo_id"], full, None, log)
            continue
        try:
            r = api.get(f"/repos/{full}")
        except ga.NetworkRequestFailed:
            raise                               # 网络错误：整次运行中断，退出码 3（协助决策 9.10 第 4 条）
        except ga.RequestFailed as e:
            log("WARNING", f"无法解析已出题仓库 {full}：{e}")
            continue
        if r.status != 200 or not isinstance(r.body, dict):
            log("WARNING", f"已出题仓库 {full} 返回 {r.status}，跳过标记")
            continue
        b = r.body
        st.upsert_repo(b["id"], b["full_name"], b.get("html_url") or "", dc.fmt_iso(now))
        st.set_repo_status(b["id"], "questioned", None, added)
        _baseline_questioned(api, st, cfg, directions, b["id"], b["full_name"], b, log)


def learner_context(bank: dict) -> dict:
    return {
        "note": "以下为「已出题」信息，仅表示题库已覆盖，不代表学习结果",
        "covered_concepts": bank["covered"],
        "domain_counts": bank["domain_counts"],
        "catalog_file": "题库目录.md",
    }


# ---------------- 主流程 ----------------

def floor_hour(t: dt.datetime) -> dt.datetime:
    return t.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _make_run_id(st: stmod.Store, now: dt.datetime) -> str:
    base = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    rid, n = base, 2
    while st.run_exists(rid):
        rid, n = f"{base}-{n}", n + 1
    return rid


def screening_text(c: dict, raw: str, cfg: dict) -> str:
    """初筛语言识别的输入：仓库描述 + README 清洗后的正文，取前 3000 字。

    注：清洗后的正文按段落优先级排列，这里取的是「清洗后的前 3000 字」，不是 README 原文的前 3000 字。
    """
    sections = en.clean_readme(raw, cfg["readme_max_chars"])
    parts = [c.get("description") or ""] + [s["text"] for s in sections]
    return "\n".join(parts)[:SCREEN_TEXT_CHARS]


def _readme_for_screening(api, st: stmod.Store, c: dict, end_iso: str, run_id: str, now_iso: str) -> str:
    """取 README 原文（只对通过 min_gain_window 的候选调用）。同一窗口已缓存则复用；否则请求一次。

    结果写入 enrich_cache，深采直接复用，失败重跑时也不再请求。已有的深采对比数据（依赖、目录树）保留，
    供 M5.5 差异证据使用。
    """
    cached = st.cache_get(c["repo_id"])
    payload = cached["payload"] if cached else {}
    if payload.get("window_end") == end_iso and "readme_raw" in payload:
        return payload["readme_raw"]
    raw = en.fetch_readme_raw(api, c["full_name"])
    new = {"window_end": end_iso, "readme_raw": raw}
    deps, tree = cl.compare_data(payload)
    if deps is not None:
        new["compare"] = {"dependencies": deps, "tree_top2": tree}
    st.cache_put(c["repo_id"], run_id, now_iso, new)
    return raw


def _compared(st: stmod.Store, bank_items: list, direction: str, repo_id: int) -> list[dict]:
    """M5.5 对比项目：同方向已出题仓库中出题时间最近的 3 个，附带其题号与缓存的深采数据。"""
    out = []
    for r in st.questioned_in_direction(direction, repo_id, cl.COMPARE_MAX):
        full = r["full_name"] or ""
        ids = [it["id"] for it in bank_items
               if it.get("id") and full.lower() in {s.lower() for s in it.get("source_repos") or []}]
        cache = st.cache_get(r["repo_id"])
        deps, tree = cl.compare_data(cache["payload"] if cache else None)
        out.append({"full_name": full, "question_ids": ids, "dependencies": deps, "tree": tree})
    return out


def _pipeline(opts: Options, st: stmod.Store, now: dt.datetime, log, run_id: str, res: dict):
    """返回 (status, exit_code, note)。res 用于回传 pack 路径、窗口与 API 调用次数。"""
    cfg = dict(opts.config)

    # 2. 防重复（联网之前）
    last = st.last_success_until()
    if opts.init:
        # 初始化（v1.4）：回溯更长窗口、按倍数放大候选与入包规模；执行全部关键词；不受冷却期限制
        k = max(1, int(opts.init_scale))
        for key in ("max_candidates", "max_projects_per_pack", "min_gain_window"):
            cfg[key] = int(cfg[key]) * k
        # 同方向上限只放大 2 倍：资料库要覆盖面，不让少数热门方向（如 MCP、Agent 框架）占满名额
        cfg["per_direction_cap"] = int(cfg["per_direction_cap"]) * 2
        cfg["packed_cooldown_days"] = 0
        cfg["_all_keywords"] = True
        log("INFO", f"初始化模式：回溯 {opts.init_days} 天，规模 ×{k}（候选 {cfg['max_candidates']}、"
                    f"入包 {cfg['max_projects_per_pack']}、同方向上限 {cfg['per_direction_cap']}、"
                    f"窗口新增门槛 {cfg['min_gain_window']}）")
    if not opts.force and not opts.init and last:
        hours = (now - dc.parse_iso(last)).total_seconds() / 3600
        if hours < cfg["min_hours_between_runs"]:
            log("INFO", f"距上次成功采集仅 {hours:.1f} 小时（小于 {cfg['min_hours_between_runs']}），跳过")
            return "skipped_recent", EXIT_OK, "距上次成功不足设定小时数"

    # 3. Token
    if not opts.token:
        log("ERROR", "未设置 GITHUB_TOKEN")
        return "failed", EXIT_CONFIG, "未设置 GITHUB_TOKEN"

    # 4. 传输层与预检
    try:
        transport = opts.transport if opts.transport is not None else ga.RealTransport(cfg.get("proxy", ""))
    except ga.ConfigError as e:
        log("ERROR", str(e))
        return "failed", EXIT_CONFIG, str(e)
    api = ga.GitHubAPI(transport, opts.token, sleep=opts.sleep, now=lambda: now.timestamp(),
                       mono=time.monotonic, log=log)
    res["api"] = api
    try:
        rl = api.preflight(timeout=5)
    except ga.TransportError as e:
        log("WARNING", f"联网预检失败，本次跳过：{e}")
        return "skipped_no_network", EXIT_OK, f"预检失败：{e}"
    core = ((rl or {}).get("resources") or {}).get("core") or {}
    remaining = core.get("remaining")
    if remaining is not None and remaining < RATE_RESERVE:
        cfg["max_candidates"] = max(1, cfg["max_candidates"] // 2)
        log("WARNING", f"核心限额剩余 {remaining}，max_candidates 减半为 {cfg['max_candidates']}")

    # 5. 窗口（UTC）。star_days 不含终点当天（方案 v1.2，9.8 a′）：
    #    终点当天的 Star 数据不完整，留到下一次运行再完整计入；起点与终点同一天时 star_days 为空。
    end = floor_hour(now)
    if opts.init:
        start = end - dt.timedelta(days=int(opts.init_days))
    elif opts.since:
        start = dt.datetime(opts.since.year, opts.since.month, opts.since.day, tzinfo=UTC)
    elif last:
        start = dc.parse_iso(last)
    else:
        start = end - dt.timedelta(days=cfg["first_run_days"])
    d1, end_date = start.date(), end.date()
    star_days = [d1 + dt.timedelta(days=i) for i in range(max(0, (end_date - d1).days))]
    res["window"] = (start, end, star_days)
    log("INFO", f"窗口 {dc.fmt_iso(start)} → {dc.fmt_iso(end)}，共 {len(star_days)} 天（不含终点当天）")
    end_iso = dc.fmt_iso(end)
    now_iso = dc.fmt_iso(now)

    # 窗口不足一天（起点与终点同一天，star_days 为空）：不出包、水位线不动、关键词断点不动（协助决策 9.9 第 2 条）
    if not star_days:
        log("INFO", "窗口不足一天，本次不出包，水位线不变")
        return "skipped_recent", EXIT_OK, "窗口不足一天"

    # 6. 扫描题库（只读），标记已出题仓库并记录基线
    bank = scan_bank(opts.paths["bank_dir"], log)
    directions = dc.load_directions(opts.paths["directions"])
    concepts = load_concepts(opts.paths["concepts"], log)
    mark_questioned(api, st, bank["source_repos"], cfg, directions, now, log)

    # 7. 发现 → Star 初筛（含 README 语言识别与复收前置条件）→ 选入（含方向上限）→ 深采 → 分类与模式 → 出包
    cands, dstats = dc.discover(api, st, cfg, directions, d1, star_days[-1], now, log)
    log("INFO", f"发现：搜索 {dstats['queries']} 次，拆分 {dstats['splits']} 次，候选 {len(cands)} 个，"
                f"过滤 {dstats['dropped']}")

    # 初筛：Star 增长 + 文档语言（描述 + README 清洗后前 3000 字，协助决策 9.9 第 3 条）
    min_gain = cfg["min_gain_window"]
    days = max(1, len(star_days))          # 窗口天数：复收的增长比较用「日均新增」（协助决策 9.10 第 2 条）
    readmes: dict[int, str] = {}           # repo_id → README 原文；深采复用，不再请求
    gained = []
    skipped: list[dict] = []               # 被跳过的项目：保持 seen，下次自动重试；runs.note 与预览列出
    # 第一遍：Star 历史（每个候选 1 次请求）
    pre = []
    for i, c in enumerate(cands, 1):
        row = st.get_repo(c["repo_id"]) or {}
        snap = st.latest_snapshot(c["repo_id"])
        try:
            g = stars.gain_for_repo(api, c["full_name"], star_days, c["stars"],
                                    snap["stars"] if snap else None)
        except ga.RequestFailed as e:
            log("WARNING", f"跳过 {c['full_name']}：Star 历史请求失败（{e}）")
            skipped.append({"full_name": c["full_name"], "reason": f"Star 历史请求失败（{e}）"})
            continue
        pre.append((c, row, g))
        if opts.verbose and i % 100 == 0:
            print(f"  Star 历史 {i}/{len(cands)}")

    # 初始化：候选很多，只对增长靠前的一批取 README（另给非英语候选单独留名额），控制请求次数
    if opts.init:
        limit0 = opts.max_projects or cfg["max_projects_per_pack"]
        passing = sorted([x for x in pre if x[2]["gain"] >= min_gain], key=lambda x: -x[2]["gain"])
        pool = passing[: limit0 * 6]
        ids = {x[0]["repo_id"] for x in pool}
        non_en = [x for x in passing if x[0]["repo_id"] not in ids and dc.is_non_english_candidate(x[0])]
        pool += non_en[: limit0 * 2]
        log("INFO", f"初始化：Star 历史 {len(pre)} 个，达到门槛 {len(passing)} 个，取 README 的 {len(pool)} 个")
        pre = pool

    thin = 0
    for c, row, g in pre:
        daily = g["gain"] / days
        if row.get("status") == "questioned" and row.get("gain_at_first_pack") is None:
            # 第一次再被观察到：补基线。row 是进入本次运行前的快照，所以这一次不据此复收
            st.set_gain_baseline(c["repo_id"], daily)
        # 只有通过 min_gain_window 的候选才取 README（协助决策 9.9 第 3 条，控制调用次数）；
        # 已出题仓库还要取最新 release，用于 M5.4 复收判断
        raw = ""
        latest = None
        if g["gain"] >= min_gain:
            try:
                raw = _readme_for_screening(api, st, c, end_iso, run_id, now_iso)
                if row.get("status") == "questioned":
                    latest = en.fetch_latest_release(api, c["full_name"], cfg["release_max_chars"])
            except ga.RequestFailed as e:
                log("WARNING", f"跳过 {c['full_name']}：README 或 release 请求失败（{e}）")
                skipped.append({"full_name": c["full_name"], "reason": f"README 或 release 请求失败（{e}）"})
                continue
            readmes[c["repo_id"]] = raw
            # 初始化要建资料库：README 清洗后太短（多为清单、壳项目）的不收
            if opts.init and len("".join(s["text"] for s in en.clean_readme(raw, cfg["readme_max_chars"]))) < INIT_MIN_README:
                thin += 1
                continue
        st.add_snapshot(c["repo_id"], c["stars"], now_iso)
        c["gain"] = g
        c["gain_daily"] = daily
        c["row"] = row
        c["latest_release"] = latest
        c["latest_tag"] = (latest or {}).get("tag")
        c["quick"] = cl.classify(directions, c.get("topics"), c.get("name"), c.get("description"), "")
        c["lang"] = langid.detect(screening_text(c, raw, cfg))
        c["lang"]["lang_group"] = langid.lang_group(c["lang"]["doc_lang"])
        gained.append(c)

    if thin:
        log("INFO", f"初始化：README 过短（清洗后不足 {INIT_MIN_README} 字）不收 {thin} 个")

    # M5.4 复收前置条件（选入之前）：已出题仓库须满足「发布新主版本」或「增长达到 2 倍」，否则不入包
    kept = []
    for c in gained:
        if c["row"].get("status") == "questioned" and c["gain"]["gain"] >= min_gain:
            upd = cl.update_reason(c["row"], now, cfg, c["latest_tag"], c["gain_daily"])
            if upd is None:
                log("INFO", f"已出题仓库未满足复收条件，不入包：{c['full_name']}")
                continue
            c["update"] = upd
        kept.append(c)
    gained = kept

    # M4.3 先写入、后计算：本次全部候选写入 candidate_gains，再用包含本次候选的基线算热度
    for c in gained:
        st.add_candidate_gain(run_id, c["repo_id"], c["lang"]["lang_group"], c["gain"]["gain"],
                              days, now_iso)
    baseline = st.baseline_rows(dc.fmt_iso(now - dt.timedelta(days=cfg["heat"]["baseline_days"])))
    view = [{"ref": c, "repo_id": c["repo_id"], "lang_group": c["lang"]["lang_group"],
             "gain": c["gain"]["gain"], "days": days, "heat": None,
             "direction": c["quick"]["direction"]} for c in gained]
    heat, cold = rank.compute_heat(view, baseline, cfg, log)
    for v in view:
        v["heat"] = heat[v["repo_id"]]
        v["ref"]["heat_score"] = v["heat"]

    # M4.4 选入（M5 起执行同方向上限，用快速分类；unclassified 不受限制）
    limit = opts.max_projects or cfg["max_projects_per_pack"]
    picked = rank.select(view, cfg, limit, cold, log)
    selected = [v["ref"] for v in picked]
    log("INFO", f"初筛 {len(gained)} 个，选入 {len(selected)} 个" + ("（冷启动）" if cold else ""))

    enriched = []
    for c in selected:
        cached = st.cache_get(c["repo_id"])
        payload = cached["payload"] if cached else {}
        if payload.get("window_end") == end_iso and "meta" in payload:
            enr = payload
            log("INFO", f"深采缓存命中，跳过请求：{c['full_name']}")
        else:
            try:
                enr = en.enrich_project(api, cfg, c["full_name"], readme_raw=readmes[c["repo_id"]])
            except ga.RequestFailed as e:
                log("WARNING", f"跳过 {c['full_name']}：深采失败（{e}）")
                skipped.append({"full_name": c["full_name"], "reason": f"深采失败（{e}）"})
                continue
            enr["window_end"] = end_iso
            enr["readme_raw"] = readmes[c["repo_id"]]
            enr["compare"] = {"dependencies": enr.get("dependencies") or [],
                              "tree_top2": enr.get("tree_top2") or []}
            st.cache_put(c["repo_id"], run_id, now_iso, enr)
        enriched.append((c, enr))

    # 深采只补充「可用文档语言」列表；文档语言本身已在初筛完成（协助决策 9.9 第 3 条）
    for c, enr in enriched:
        codes = list(enr.get("doc_langs_available") or [])
        doc_lang = c["lang"]["doc_lang"]
        if doc_lang != "und" and doc_lang not in codes:
            codes.insert(0, doc_lang)
        enr["doc_langs_available"] = codes

    # M5：深采后用含 README 的完整输入重新分类，再判断学习模式、相关题与差异证据
    covered = set(bank["covered"])
    for c, enr in enriched:
        meta = enr["meta"]
        readme_text = "\n".join(s["text"] for s in enr.get("readme_sections") or [])
        cls = cl.classify(directions, meta.get("topics"), meta.get("full_name") or c["full_name"],
                          meta.get("description"), readme_text)
        direction = cls["direction"]
        prereqs = (directions.get(direction) or {}).get("prerequisites") or []
        text = cl.build_text(meta.get("full_name"), meta.get("description"), meta.get("topics"), readme_text)
        full = meta.get("full_name") or c["full_name"]
        detail = cl.direction_detail(directions, meta.get("topics"), text)
        log("INFO", f"分类明细 {full} → {direction}（{cls['direction_confidence']}）：{cl.format_detail(detail)}")
        keys = set(prereqs) | cl.concept_hits(concepts, text)
        mode = cl.decide_mode(direction, prereqs, covered, concepts)
        upd = c.get("update")
        release_change = None
        if upd:
            mode = {"learning_mode": "update", "mode_reason": upd["text"], "prerequisites_missing": []}
            # 协助决策 9.10 第 3 条：最新 tag 与上次记录不同就填写（不论是否主版本）；tag 未变则为 null
            new_tag = c.get("latest_tag")
            old_tag = c["row"].get("last_release_tag") or None
            if new_tag and new_tag != (old_tag or ""):
                release_change = {"from": old_tag, "to": new_tag}
        diff = None
        if mode["learning_mode"] in ("delta", "update"):
            compared = _compared(st, bank["items"], direction, c["repo_id"]) if direction != "unclassified" else []
            diff = cl.diff_evidence(enr.get("dependencies") or [], enr.get("tree_top2") or [],
                                    compared, release_change)
        c["cls"] = {
            "direction": direction,
            "direction_confidence": cls["direction_confidence"],
            "secondary_directions": cls["secondary_directions"],
            "domain": cls["domain"],
            "learning_mode": mode["learning_mode"],
            "mode_reason": mode["mode_reason"],
            "prerequisites_missing": mode["prerequisites_missing"],
            "related_questions": cl.related_questions(bank["items"], keys),
            "diff_evidence": diff,
        }

    notes = []
    if last and not opts.since:
        gap_days = (end_date - dc.parse_iso(last).date()).days
        notes.append(f"上次成功采集为 {last[:10]}；本包覆盖之后 {gap_days} 天")
    elif not last and not opts.since:
        notes.append(f"首次运行：窗口为最近 {cfg['first_run_days']} 天")
    if opts.init:
        notes = [f"初始化：回溯最近 {opts.init_days} 天，按正常巡检 {opts.init_scale} 倍规模收录"]
    if cold:
        notes.append("冷启动：热度分未启用，按「窗口新增 ÷ 天数」排序")
    if any(c["gain"]["estimated"] for c, _ in enriched):
        notes.append("热度为估算（Star 历史接口不可用，按快照差值）")

    projects = [pack.project_record(c, enr, c["gain"]) for c, enr in enriched]
    packobj = pack.build_pack(
        run={"run_id": run_id, "window_start": dc.fmt_iso(start), "window_end": end_iso,
             "star_days": [d.isoformat() for d in star_days], "gap_note": "；".join(notes),
             "skipped": skipped},
        learner=learner_context(bank),
        projects=projects,
    )

    if opts.dry_run:
        log("INFO", f"dry-run：不写采集包、不改水位线，本应入包 {len(projects)} 个")
        res["dry_projects"] = [(p["full_name"], p["stars_gained_window"]) for p in projects]
        return "success", EXIT_OK, "dry-run"

    pack_path = pack.write_pack(opts.paths["out_dir"], packobj, now)
    try:
        n_lib = 0 if not opts.paths.get("library") else library.update(opts.paths["library"], packobj, concepts, os.path.basename(pack_path),
                               now.astimezone().date().isoformat())
        log("INFO", f"资料库已更新：写入 {n_lib} 个项目")
    except Exception:                       # 资料库只是整理产物，失败不影响采集结果
        log("WARNING", "资料库更新失败：\n" + traceback.format_exc())
    for c, enr in enriched:
        rel = (enr.get("latest_release") or {}).get("tag")
        st.mark_packed(c["repo_id"], run_id, dc.fmt_iso(now), c["gain_daily"], rel)
        st.set_direction(c["repo_id"], c["cls"]["direction"])
    # M4.2：关键词查询断点只在出包成功后保存，失败的运行不跳过任何查询
    for lang, pos in (dstats.get("rotation") or {}).items():
        st.meta_set_json(f"kw_rotation_{lang}", {"pos": pos})
    # 水位线只前进不回退（第 9.7 节 (c)）：--since 等情况下窗口终点可能早于原水位线
    new_wm = max(dc.parse_iso(last), end) if last else end
    st.meta_set("last_success_until", dc.fmt_iso(new_wm))
    res["pack"] = pack_path
    log("INFO", f"出包完成：{os.path.basename(pack_path)}，{len(projects)} 个项目")
    # 协助决策 9.10 第 6 条：runs.note 记录跳过的个数（被跳过的项目保持 seen，下次自动重试）
    return "success", EXIT_OK, (f"跳过 {len(skipped)} 个项目（保持 seen，下次运行自动重试）" if skipped else "")


def run(opts: Options) -> int:
    now = opts.clock().astimezone(UTC)
    if not acquire_lock(opts.paths["lock"]):
        print("另一个采集实例正在运行（collect.lock 未过期），本次退出。")
        return EXIT_LOCKED
    try:
        return _run_locked(opts, now)
    finally:
        release_lock(opts.paths["lock"])


def _run_locked(opts: Options, now: dt.datetime) -> int:
    if opts.config is None:
        opts.config = load_config(opts.paths["config"])
    log = RunLog(opts.paths["log_dir"], opts.token, opts.clock, opts.verbose)
    log("INFO", f"开始运行（dry_run={opts.dry_run}, force={opts.force}）")

    tmpdir = None
    work_db = opts.paths["state_db"]
    if opts.dry_run:
        tmpdir = tempfile.mkdtemp(prefix="collect_dry_")
        work_db = os.path.join(tmpdir, "state.db")
        if os.path.exists(opts.paths["state_db"]):
            shutil.copy2(opts.paths["state_db"], work_db)

    st = stmod.Store(work_db)
    run_id = _make_run_id(st, now)
    res: dict = {}
    try:
        try:
            status, code, note = _pipeline(opts, st, now, log, run_id, res)
        except ga.FatalNetwork as e:
            status, code, note = "partial", EXIT_PARTIAL, f"中途网络中断：{e}"
            log("ERROR", note)
        except ga.NetworkRequestFailed as e:
            # 网络错误、连接失败或 5xx 重试后仍失败：退出码 3，记 partial，水位线不动（协助决策 9.10 第 4 条）
            status, code, note = "partial", EXIT_PARTIAL, f"网络或服务器错误，重试后仍失败：{e}"
            log("ERROR", note)
        except ga.BudgetExhausted as e:
            status, code, note = "partial", EXIT_PARTIAL, f"限额等待超过上限：{e}"
            log("ERROR", note)
        except Exception as e:  # 未预期错误：记录（已脱敏）后退出
            status, code, note = "failed", EXIT_UNEXPECTED, f"未预期错误：{type(e).__name__}"
            log("ERROR", "未预期错误：\n" + ga.redact(traceback.format_exc(), opts.token))
        if status != "success":
            st.delete_candidate_gains(run_id)     # 失败的运行不进入热度基线
        window = res.get("window")
        api = res.get("api")
        st.add_run(
            run_id=run_id,
            started_at=dc.fmt_iso(now),
            finished_at=dc.fmt_iso(opts.clock()),
            status=status,
            window_start=dc.fmt_iso(window[0]) if window else None,
            window_end=dc.fmt_iso(window[1]) if window else None,
            pack_file=os.path.basename(res["pack"]) if res.get("pack") else None,
            api_calls=api.calls if api else 0,
            note=ga.redact(note or "", opts.token),
        )
        st.close()
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    note = ga.redact(note or "", opts.token)     # 控制台输出同样脱敏
    if opts.dry_run:
        print(f"[dry-run] 状态 {status}；本应入包：")
        for name, gain in res.get("dry_projects", []):
            print(f"  {name}  窗口新增 {gain}")
    else:
        print(f"状态 {status}" + (f"；采集包 {res['pack']}" if res.get("pack") else "") +
              (f"；{note}" if note and status != "success" else ""))
    return code


def parse_args(argv):
    p = argparse.ArgumentParser(description="GitHub 学习采集器")
    p.add_argument("--force", action="store_true", help="忽略防重复限制")
    p.add_argument("--since", type=lambda s: dt.date.fromisoformat(s), help="窗口起点 YYYY-MM-DD")
    p.add_argument("--max", type=int, dest="max_projects", help="本次入包上限")
    p.add_argument("--dry-run", action="store_true", help="不写采集包、不改水位线")
    p.add_argument("--fixtures", help="用夹具目录代替真实网络（测试用）")
    p.add_argument("--verbose", action="store_true", help="同时打印日志")
    p.add_argument("--init", action="store_true", help="初始化：回溯 --days 天，按 --scale 倍规模收录")
    p.add_argument("--days", type=int, default=90, help="初始化回溯天数（默认 90）")
    p.add_argument("--scale", type=int, default=5, help="初始化规模倍数（默认 5）")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    paths = default_paths()
    try:
        cfg = load_config(paths["config"])
    except (OSError, ValueError) as e:
        print(f"配置错误：无法读取 config.json（{e}）")
        return EXIT_CONFIG
    token = (os.environ.get("GITHUB_TOKEN") or "").strip() or None
    if not token:
        print(TOKEN_HELP)
        return EXIT_CONFIG
    transport = ga.FixtureTransport(args.fixtures) if args.fixtures else None
    opts = Options(paths=paths, token=token, transport=transport, config=cfg,
                   force=args.force, since=args.since, max_projects=args.max_projects,
                   dry_run=args.dry_run, verbose=args.verbose,
                   init=args.init, init_days=args.days, init_scale=args.scale)
    return run(opts)


if __name__ == "__main__":
    sys.exit(main())
