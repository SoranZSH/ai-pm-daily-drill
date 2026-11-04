"""方向分类、学习模式、相关题与差异证据（方案 M5.1–M5.5）。

只做计算：不联网、不读写数据库。调用方（collect.py）负责取数据、写结果。

- 方向得分 = 命中的 topic 数 × 3 + 命中的关键词数 × 1；关键词跨所有语言，同一关键词只计一次。
- 选入阶段的「快速分类」只用 topics、仓库名、描述（协助决策 9.2 P9）；深采后再加上 README 重新分类。
- 英文或缩写关键词按词边界匹配（避免 "sft" 命中 "soft"），其余按子串匹配，大小写不敏感。
"""
from __future__ import annotations

import datetime as dt
import re

UTC = dt.timezone.utc
TOPIC_WEIGHT = 3
KEYWORD_WEIGHT = 1
README_CHARS = 3000        # 与方案一致：README 清洗后前 3000 字
RELATED_MAX = 8            # M5.3：最多 8 条相关题
COMPARE_MAX = 3            # M5.5：最多 3 个对比项目
_ASCII_TERM = re.compile(r"[a-z0-9][a-z0-9 .+\-]*")


def _has(text: str, term: str) -> bool:
    """text 须已转为小写。"""
    t = term.lower().strip()
    if not t:
        return False
    if _ASCII_TERM.fullmatch(t):
        return re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", text) is not None
    return t in text


def major_of(tag: str | None) -> int | None:
    """从 release 标签中取第一个整数作为主版本号（v2.0.0 → 2）；取不到返回 None。"""
    if not tag:
        return None
    m = re.search(r"\d+", tag)
    return int(m.group()) if m else None


def parse_time(s: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def build_text(name: str | None, description: str | None, topics: list | None, readme: str = "") -> str:
    """供关键词与别名匹配的文本：名称、描述、topics、README 前 3000 字（已小写）。"""
    return "\n".join([name or "", description or "", " ".join(topics or []),
                      (readme or "")[:README_CHARS]]).lower()


# ---------------- M5.1 方向分类 ----------------

def direction_scores(directions: dict, topics: list | None, text: str) -> dict:
    tl = {t.lower() for t in topics or []}
    out = {}
    for key, d in directions.items():
        tcount = sum(1 for t in d.get("topics") or [] if t.lower() in tl)
        kws = {w.lower() for words in (d.get("keywords") or {}).values() for w in words}
        kcount = sum(1 for w in kws if _has(text, w))
        out[key] = TOPIC_WEIGHT * tcount + KEYWORD_WEIGHT * kcount
    return out


def direction_detail(directions: dict, topics: list | None, text: str, top_n: int = 3) -> list[dict]:
    """M5.1 得分明细（仅用于日志）：列出得分大于 0 的方向（最多 top_n 个），附命中的 topics 与关键词。

    排序与 classify 一致：得分降序，平局按方向词表书写顺序。
    """
    order = list(directions)
    tl = {t.lower() for t in topics or []}
    out = []
    for key in order:
        d = directions[key]
        hit_topics = sorted(t for t in d.get("topics") or [] if t.lower() in tl)
        kws = sorted({w.lower() for words in (d.get("keywords") or {}).values() for w in words})
        hit_kws = [w for w in kws if _has(text, w)]
        score = TOPIC_WEIGHT * len(hit_topics) + KEYWORD_WEIGHT * len(hit_kws)
        if score > 0:
            out.append({"direction": key, "score": score, "topics": hit_topics, "keywords": hit_kws})
    out.sort(key=lambda x: (-x["score"], order.index(x["direction"])))
    return out[:top_n]


def format_detail(detail: list[dict]) -> str:
    """把得分明细格式化成一行日志文本。"""
    if not detail:
        return "无任何方向命中（归为 unclassified）"
    parts = []
    for x in detail:
        hits = []
        if x["topics"]:
            hits.append("topics: " + ", ".join(x["topics"]))
        if x["keywords"]:
            hits.append("关键词: " + ", ".join(x["keywords"]))
        parts.append(f"{x['direction']} 得分 {x['score']}（{'；'.join(hits)}）")
    return " | ".join(parts)


def _unclassified() -> dict:
    return {"direction": "unclassified", "direction_confidence": "low",
            "secondary_directions": [], "domain": None}


def classify(directions: dict, topics: list | None, name: str | None, description: str | None,
             readme: str = "") -> dict:
    """返回 {direction, direction_confidence, secondary_directions, domain}。

    平局按方向词表的书写顺序取先出现者；最高分为 0 → unclassified。
    """
    order = list(directions)
    if not order:
        return _unclassified()
    text = build_text(name, description, topics, readme)
    scores = direction_scores(directions, topics, text)
    ranked = sorted(order, key=lambda k: (-scores[k], order.index(k)))
    top = ranked[0]
    s1 = scores[top]
    if s1 == 0:
        return _unclassified()
    s2 = scores[ranked[1]] if len(ranked) > 1 else 0
    if s1 >= 3 and s1 - s2 >= 2:
        conf = "high"
    elif s1 >= 2:
        conf = "medium"
    else:
        conf = "low"
    secondary = [k for k in ranked[1:] if scores[k] >= 2][:2]
    return {"direction": top, "direction_confidence": conf,
            "secondary_directions": secondary, "domain": directions[top].get("domain")}


# ---------------- M5.2 / M5.3 覆盖与相关题 ----------------

def concept_hits(concepts: dict | None, text: str) -> set:
    """README 等文本中命中某个概念别名的概念键（M5.3）。text 须已小写。"""
    return {k for k, c in (concepts or {}).items()
            if any(_has(text, a) for a in c.get("aliases") or [])}


def related_questions(items: list, keys: set) -> list:
    """题库中 concepts 与 keys 有交集的题：F 题在前，最多 8 条。"""
    hits = [it for it in items if it.get("id") and set(it.get("concepts") or []) & keys]
    hits.sort(key=lambda it: 0 if (it.get("level") or "F") == "F" else 1)
    return [{"id": it["id"], "level": it.get("level") or "F", "q_cn": it.get("q_cn")}
            for it in hits[:RELATED_MAX]]


# ---------------- M5.4 学习模式 ----------------

NOTE_NO_COMPARED = "本方向尚无已出题项目可对比，请参考 题库目录.md 中同领域的题目判断差异"
NOTE_NO_CACHE = "对比项目无缓存数据"


def update_reason(row: dict | None, now: dt.datetime, cfg: dict, latest_tag: str | None,
                  gain_daily: float) -> dict | None:
    """复收（update）条件。返回 {kind, text} 或 None。

    须同时满足：状态为已出题；距 questioned_at ≥ revisit_min_days；
    且满足其一：最新 release 主版本号 > 上次记录的主版本号（发布触发）；
    或本次日均新增 ≥ 2 × gain_at_first_pack（增长触发）。
    gain_at_first_pack 的语义是「首次记录时的日均新增」（gain ÷ 窗口天数），不是窗口总量；
    为空时增长规则不生效，collect.py 在第一次观察到该仓库时补上基线（当次不据此复收）。
    上次记录缺失（无 release 记录）时，发布规则视为不满足。
    """
    if not row or row.get("status") != "questioned" or not row.get("questioned_at"):
        return None
    if (now - parse_time(row["questioned_at"])).days < cfg["revisit_min_days"]:
        return None
    new_major = major_of(latest_tag)
    old_major = major_of(row.get("last_release_tag"))
    if new_major is not None and old_major is not None and new_major > old_major:
        return {"kind": "release", "text": f"发布触发：上次出题后发布了 v{new_major}"}
    base = row.get("gain_at_first_pack")
    if base and gain_daily >= 2 * base:
        return {"kind": "gain",
                "text": f"增长触发：近期日均新增 {gain_daily:.1f}，达到首次记录时（{base:.1f}/日）的 2 倍以上"}
    return None


def decide_mode(direction: str, prereqs: list, covered: set, concepts: dict | None) -> dict:
    """foundation / delta（update 由 update_reason 先行判定）。未识别方向按基础模式处理。"""
    if direction == "unclassified":
        return {"learning_mode": "foundation", "mode_reason": "未识别到方向，按基础模式处理",
                "prerequisites_missing": []}
    missing = [k for k in prereqs if k not in covered]
    if missing:
        names = [{"key": k, "name": (concepts or {}).get(k, {}).get("name", k)} for k in missing]
        return {"learning_mode": "foundation",
                "mode_reason": f"{direction} 方向有 {len(missing)} 个前置概念尚未出题",
                "prerequisites_missing": names}
    return {"learning_mode": "delta", "mode_reason": "本方向前置概念均已出题，侧重与已出题项目的差异",
            "prerequisites_missing": []}


# ---------------- M5.5 差异证据 ----------------

def compare_data(payload: dict | None) -> tuple[list | None, list | None]:
    """从 enrich_cache 的载荷取 (依赖列表, 目录树)；没有深采数据时返回 (None, None)。"""
    if not payload:
        return None, None
    src = payload.get("compare") or (payload if "meta" in payload else None)
    if not src:
        return None, None
    return list(src.get("dependencies") or []), list(src.get("tree_top2") or [])


def _first_level_dirs(tree: list) -> list:
    return [p[:-1] for p in tree if p.endswith("/") and p.count("/") == 1]


def _norm_module(name: str) -> str:
    return re.sub(r"[-_]", "", name.lower())


def diff_evidence(deps: list, tree: list, compared: list, release_change: dict | None) -> dict:
    """compared 每项：{full_name, question_ids, dependencies, tree}，其中 dependencies/tree 为 None 表示无缓存。

    对比项目为空时，note 写 NOTE_NO_COMPARED（题库重建后常见：前置概念已出题，但没有关联仓库）；
    对比项目存在但任一项目无缓存时，新增依赖与新增目录字段为空列表，note 写 NOTE_NO_CACHE。
    """
    note = ""
    new_deps: list = []
    new_mods: list = []
    complete = bool(compared) and all(c.get("dependencies") is not None and c.get("tree") is not None
                                      for c in compared)
    if not compared:
        note = NOTE_NO_COMPARED
    elif not complete:
        note = NOTE_NO_CACHE
    if complete:
        dep_set = {d.lower() for c in compared for d in c["dependencies"]}
        mod_set = {_norm_module(m) for c in compared for m in _first_level_dirs(c["tree"])}
        new_deps = [d for d in deps if d.lower() not in dep_set]
        new_mods = [m for m in _first_level_dirs(tree) if _norm_module(m) not in mod_set]
    return {
        "compared_with": [{"full_name": c["full_name"], "question_ids": c["question_ids"]} for c in compared],
        "new_dependencies": new_deps,
        "new_modules_in_tree": new_mods,
        "release_change": release_change,
        "note": note,
    }
