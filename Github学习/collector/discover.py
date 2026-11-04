"""发现（方案 M3.7）。

- 方向词表 方向词表.json 在 M3 就建立（v1.1）：本模块只读取其中的 topics 用于搜索。
- 方向上限（per_direction_cap）从 M5 起才执行（v1.1 第 9.2 节 P9）；本模块不做方向分类。
- should_revisit() 在 M5 实现：已出题仓库只有超过 revisit_min_days 天才继续看（完整复收条件见 collect.py）。
- 关键词渠道（kw:）在 M4.2 实现（_keyword_discovery），断点只在出包成功后由调用方保存。
"""
from __future__ import annotations

import datetime as dt
import json
import math

SEARCH_TOTAL_LIMIT = 1000  # 搜索结果上限；超过则拆分日期区间


def load_directions(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def all_topics(directions: dict) -> list[str]:
    """所有启用方向的 topics，去重并保持方向词表中的书写顺序。"""
    seen: list[str] = []
    for d in directions.values():
        for t in d.get("topics", []):
            if t not in seen:
                seen.append(t)
    return seen


def fmt_iso(d: dt.datetime) -> str:
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)     # 题库里的日期只有年月日


def should_revisit(repo_row: dict, now: dt.datetime, cfg: dict) -> bool:
    """已出题仓库是否进入复收考虑（M5.4 的时间门槛）：距 questioned_at ≥ revisit_min_days。

    release 与 Star 条件要到初筛、深采后才能判断，由 collect.py 处理；这里只决定是否继续看它。
    """
    q = repo_row.get("questioned_at")
    if not q:
        return False
    return (now - parse_iso(q)).days >= cfg["revisit_min_days"]


def is_awesome(item: dict) -> bool:
    name = (item.get("name") or "").lower()
    desc = (item.get("description") or "").lower()
    return name.startswith("awesome") or "awesome list" in desc or "curated list" in desc


def keyword_pairs(directions: dict, lang: str) -> list[tuple[str, str]]:
    """某语言的关键词查询队列：按「第 k 个关键词」轮换各方向（先每个方向的第 1 个，再第 2 个……）。"""
    maxk = max((len((d.get("keywords") or {}).get(lang, [])) for d in directions.values()), default=0)
    pairs: list[tuple[str, str]] = []
    for k in range(maxk):
        for key, d in directions.items():
            kws = (d.get("keywords") or {}).get(lang, [])
            if k < len(kws):
                pairs.append((key, kws[k]))
    return pairs


def pick_keyword_queries(pairs: list, pointer: int, n: int) -> tuple[list, int]:
    """从断点 pointer 起取最多 n 个查询，到队尾后回绕；返回 (选中的查询, 下次断点)。"""
    if not pairs:
        return [], 0
    start = pointer % len(pairs)
    picked = [pairs[(start + i) % len(pairs)] for i in range(min(n, len(pairs)))]
    return picked, (start + len(picked)) % len(pairs)


def _range_query(kind: str, topic: str, lo: dt.date, hi: dt.date | None, cfg: dict) -> str:
    if kind.startswith("kw:"):
        # 关键词渠道（M4.2，v1.4）：找「窗口内有更新、Star 达到门槛」的活跃项目，与老项目渠道同一思路。
        # v1.3 之前按「窗口内新建」查询，日常运行窗口只有 1 天，96 次查询只命中 14 个仓库，故改。
        lang = kind.split(":", 1)[1]
        mins = cfg["languages"]["keyword_min_stars"]
        kmin = mins.get(lang, mins["default"])
        term = f'"{topic}"' if " " in topic else topic      # 含空格的关键词按短语匹配（协助决策 9.9 第 6 条）
        if hi is None:
            return f"{term} in:name,description,readme pushed:>={lo.isoformat()} stars:>={kmin}"
        return f"{term} in:name,description,readme pushed:{lo.isoformat()}..{hi.isoformat()} stars:>={kmin}"
    if kind == "new":
        return (f"topic:{topic} created:{lo.isoformat()}..{hi.isoformat()} "
                f"stars:>={cfg['new_repo_min_stars']}")
    # revival：首次查询用 pushed:>=d1（与方案一致）；拆分后用闭区间
    if hi is None:
        return f"topic:{topic} pushed:>={lo.isoformat()} stars:>={cfg['revival_min_stars']}"
    return f"topic:{topic} pushed:{lo.isoformat()}..{hi.isoformat()} stars:>={cfg['revival_min_stars']}"


def _search_range(api, kind: str, topic: str, lo: dt.date, hi: dt.date | None,
                  today: dt.date, cfg: dict, stats: dict, log) -> list[dict]:
    q = _range_query(kind, topic, lo, hi, cfg)
    stats["queries"] += 1
    r = api.search_repos(q)
    if r.status != 200:
        stats["errors"] += 1
        log("WARNING", f"搜索失败（{r.status}）：{q}")
        return []
    body = r.body or {}
    total = int(body.get("total_count", 0))
    items = body.get("items", []) or []
    log("INFO", f"搜索 total_count={total}：{q}")      # 第 9.7 节 (d)：每次查询都记录
    if total <= SEARCH_TOTAL_LIMIT:
        return items
    eff_hi = hi or today
    if eff_hi > lo:
        stats["splits"] += 1
        mid = lo + dt.timedelta(days=(eff_hi - lo).days // 2)
        return (_search_range(api, kind, topic, lo, mid, today, cfg, stats, log)
                + _search_range(api, kind, topic, mid + dt.timedelta(days=1), eff_hi,
                                today, cfg, stats, log))
    stats["truncated"] += 1
    log("WARNING", f"truncated：单日仍有 {total} 条结果，只取前 {len(items)} 条：{q}")
    return items


def _merge(cands: dict, item: dict, channel: str) -> None:
    rid = item["id"]
    if rid not in cands:
        cands[rid] = {
            "repo_id": rid,
            "full_name": item.get("full_name"),
            "html_url": item.get("html_url"),
            "name": item.get("name") or "",
            "description": item.get("description"),
            "topics": list(item.get("topics") or []),
            "language": item.get("language"),
            "license": (item.get("license") or {}).get("spdx_id"),
            "created_at": item.get("created_at"),
            "pushed_at": item.get("pushed_at"),
            "stars": int(item.get("stargazers_count") or 0),
            "fork": bool(item.get("fork")),
            "archived": bool(item.get("archived")),
            "channels": [],
        }
    if channel not in cands[rid]["channels"]:
        cands[rid]["channels"].append(channel)


def _keyword_discovery(api, st, cfg: dict, directions: dict, d1: dt.date, d2: dt.date,
                       cands: dict, stats: dict, log) -> None:
    """M4.2：每种非英语语言每次最多 keyword_queries_per_run 个查询，超出时从断点轮换。

    断点不在这里写入：stats['rotation'] 只记录「下次从哪里开始」，由调用方在出包成功后保存。
    """
    n = int(cfg["languages"].get("keyword_queries_per_run", 12))
    run_all = bool(cfg.get("_all_keywords"))          # 初始化：执行全部关键词，不推进断点
    for lang in cfg["languages"]["enabled"]:
        if lang == "en":
            continue
        pairs = keyword_pairs(directions, lang)
        if not pairs:
            continue
        pointer = int((st.meta_get_json(f"kw_rotation_{lang}") or {}).get("pos", 0))
        if run_all:
            picked, nxt = list(pairs), pointer
        else:
            picked, nxt = pick_keyword_queries(pairs, pointer, n)
        log("INFO", f"关键词发现 {lang}：本次 {len(picked)} 个查询（队列 {len(pairs)} 个，断点 {pointer % len(pairs)}）")
        for _key, kw in picked:
            items = _search_range(api, f"kw:{lang}", kw, d1, None, d2, cfg, stats, log)
            for it in items:
                _merge(cands, it, f"kw:{lang}:{kw}")
        stats["rotation"][lang] = nxt


def discover(api, st, cfg: dict, directions: dict, d1: dt.date, d2: dt.date,
             now: dt.datetime, log) -> tuple[list[dict], dict]:
    """返回 (候选列表, 统计)。候选按 Star 数降序，最多 cfg['max_candidates'] 个。

    d1 为窗口第一天，d2 为窗口最后一天（UTC 日期，含两端；终点当天不在窗口内，由调用方传入）。
    """
    stats = {"queries": 0, "splits": 0, "truncated": 0, "errors": 0,
             "found": 0, "dropped": {}, "rotation": {}}
    cands: dict = {}
    for topic in all_topics(directions):
        items = _search_range(api, "new", topic, d1, d2, d2, cfg, stats, log)
        for it in items:
            _merge(cands, it, f"new:topic:{topic}")
        items = _search_range(api, "revival", topic, d1, None, d2, cfg, stats, log)
        for it in items:
            _merge(cands, it, f"revival:topic:{topic}")
    _keyword_discovery(api, st, cfg, directions, d1, d2, cands, stats, log)
    stats["found"] = len(cands)

    now_iso = fmt_iso(now)
    out: list[dict] = []

    def drop(reason: str) -> None:
        stats["dropped"][reason] = stats["dropped"].get(reason, 0) + 1

    for c in cands.values():
        st.upsert_repo(c["repo_id"], c["full_name"], c["html_url"] or "", now_iso)
        if c["fork"] or c["archived"] or is_awesome(c):
            reason = "fork" if c["fork"] else ("archived" if c["archived"] else "awesome")
            st.set_repo_status(c["repo_id"], "skipped", reason)
            drop(reason)
            continue
        row = st.get_repo(c["repo_id"])
        status = row["status"]
        if status == "skipped":
            drop("skipped")
            continue
        if status == "packed" and row.get("packed_at"):
            days = (now - parse_iso(row["packed_at"])).days
            if days < cfg["packed_cooldown_days"]:
                drop("cooldown")
                continue
        if status == "questioned" and not should_revisit(row, now, cfg):
            drop("questioned")
            continue
        out.append(c)

    return truncate_candidates(out, cfg, stats), stats


def is_non_english_candidate(c: dict) -> bool:
    """截断前的粗判：来自非英语关键词渠道，或描述明显不是英语。

    描述通常很短，langid.detect 的 40 字门槛会把它判成 und，所以这里先按文字系统直接判断
    （中日韩、西里尔字母占比 ≥ 20%），拉丁文字再交给模型（描述 ≥ 20 字时）。
    """
    if any(ch.startswith("kw:") for ch in c.get("channels", [])):
        return True
    text = c.get("description") or ""
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 4:
        return False
    non_latin = sum(1 for ch in letters if ord(ch) > 0x024F)
    if non_latin / len(letters) >= 0.2:
        return True
    if len(letters) < 20:
        return False
    try:
        import langid
        lang = langid.detect(text + " " + text)["doc_lang"] if len(letters) < 40 else langid.detect(text)["doc_lang"]
    except Exception:
        return False
    return lang not in ("en", "und")


def truncate_candidates(out: list[dict], cfg: dict, stats: dict | None = None) -> list[dict]:
    """候选截断（v1.4）：先按 Star 降序给非英语候选预留 ceil(max_candidates × min_non_english_share) 个名额，
    剩余名额再按 Star 降序从全部候选里补满。

    v1.3 之前直接取总 Star 最高的 max_candidates 个，非英语项目 Star 普遍较少，几乎都在这一步被截掉。
    """
    limit = int(cfg["max_candidates"])
    share = float(cfg.get("languages", {}).get("min_non_english_share", 0) or 0)
    reserve = math.ceil(limit * share)
    by_stars = sorted(out, key=lambda c: c["stars"], reverse=True)
    non_en = [c for c in by_stars if is_non_english_candidate(c)][:reserve]
    chosen_ids = {c["repo_id"] for c in non_en}
    rest = [c for c in by_stars if c["repo_id"] not in chosen_ids][: max(0, limit - len(non_en))]
    result = sorted(non_en + rest, key=lambda c: c["stars"], reverse=True)
    if stats is not None:
        stats["non_english_reserved"] = len(non_en)
    return result
