"""热度标准化与选入（方案 M4.3、M4.4；方向上限 M5）。

热度是「相对本语言组近期候选」的简化异常分，不是热点监测设计中的预测上界。
以后接入预测模型时，替换 compute_heat() 即可，选入规则不变。
"""
from __future__ import annotations

import math
import statistics

MAD_FLOOR = 0.25      # MAD 小于此值时取此值，避免除以接近 0 的数
MAD_SCALE = 1.4826    # MAD 换算为标准差的常数
UNCAPPED = "unclassified"   # 未识别方向的候选不受方向上限约束（方案 M4.4 第 2 条）


def xval(gain: int, days: int) -> float:
    return math.log(1 + gain / days)


def robust_stats(xs: list[float]) -> tuple[float, float]:
    m = statistics.median(xs)
    s = statistics.median([abs(x - m) for x in xs])
    return m, max(s, MAD_FLOOR)


def compute_heat(rows: list[dict], baseline: list[dict], cfg: dict, log) -> tuple[dict, bool]:
    """返回 ({repo_id: heat 或 None}, 是否冷启动)。

    rows：本次候选 [{repo_id, lang_group, gain, days}]，必须已写入 candidate_gains（先写入、后计算）；
    baseline：窗口内 candidate_gains 的全部记录（包含本次候选）。
    """
    min_n = cfg["heat"]["min_group_samples"]
    all_x = [xval(b["gain"], b["days"]) for b in baseline]
    if len(all_x) < min_n:
        log("INFO", f"冷启动：热度分未启用（合并基线样本 {len(all_x)} < {min_n}）")
        return {r["repo_id"]: None for r in rows}, True
    merged = robust_stats(all_x)
    stats_by_group: dict[str, tuple[float, float]] = {}
    for g in sorted({r["lang_group"] for r in rows}):
        xs = [xval(b["gain"], b["days"]) for b in baseline if b["lang_group"] == g]
        if len(xs) >= min_n:
            stats_by_group[g] = robust_stats(xs)
        else:
            stats_by_group[g] = merged
            log("INFO", f"语言组 {g} 历史样本 {len(xs)} < {min_n}，改用合并基线")
    out = {}
    for r in rows:
        m, s = stats_by_group[r["lang_group"]]
        out[r["repo_id"]] = (xval(r["gain"], r["days"]) - m) / (MAD_SCALE * s)
    return out, False


def _score_key(cold: bool):
    """排序键（越小越靠前）：热度降序；冷启动时按 gain ÷ days 降序。"""
    if cold:
        return lambda c: -(c["gain"] / c["days"])
    return lambda c: -c["heat"]


def select(cands: list[dict], cfg: dict, limit: int, cold: bool, log) -> list[dict]:
    """M4.4 选入（含 M5 方向上限）。cands 每项含 gain、days、heat（冷启动时为 None）、lang_group，
    以及 direction（快速分类结果；缺省或 unclassified 时不受上限约束）。

    1. 丢弃 gain < min_gain_window，或（非冷启动时）heat < min_heat_score 的候选；
    2. 按排序键依次选入，同一方向不超过 per_direction_cap（超出的跳过，留给配额替换）；
    3. 非英语配额：入包中非英语占比 ≥ min_non_english_share（向上取整），不足则用非英语最高分替换英语最低分，
       替换时同样遵守方向上限；没有合格候选时不强行补足（仅记录日志）。
    """
    min_gain = cfg["min_gain_window"]
    min_heat = cfg["heat"]["min_heat_score"]
    cap = cfg.get("per_direction_cap")
    key = _score_key(cold)
    eligible = [c for c in cands
                if c["gain"] >= min_gain and (cold or (c["heat"] is not None and c["heat"] >= min_heat))]
    eligible.sort(key=key)

    counts: dict[str, int] = {}

    def direction(c):
        return c.get("direction") or UNCAPPED

    def allowed(c) -> bool:
        d = direction(c)
        return cap is None or d == UNCAPPED or counts.get(d, 0) < cap

    def take(c) -> None:
        d = direction(c)
        if d != UNCAPPED:
            counts[d] = counts.get(d, 0) + 1

    def give(c) -> None:
        d = direction(c)
        if d != UNCAPPED:
            counts[d] -= 1

    selected: list[dict] = []
    chosen: set[int] = set()
    capped = 0
    for c in eligible:
        if len(selected) >= limit:
            break
        if allowed(c):
            selected.append(c)
            chosen.add(id(c))
            take(c)
        else:
            capped += 1
    if capped:
        log("INFO", f"同方向上限 {cap}：跳过 {capped} 个超出上限的候选")

    def non_en(c):
        return c["lang_group"] != "en"

    share = cfg["languages"]["min_non_english_share"]
    need = math.ceil(round(share * len(selected), 6))
    pool = [c for c in eligible if id(c) not in chosen and non_en(c)]     # 已按分数降序
    n_in = sum(1 for c in selected if non_en(c))
    replaced = 0
    while n_in < need:
        en_idx = [i for i, c in enumerate(selected) if not non_en(c)]
        if not en_idx:
            break
        worst = max(en_idx, key=lambda i: key(selected[i]))    # 英语组中分数最低的
        e = selected[worst]
        give(e)
        j = next((j for j, p in enumerate(pool) if allowed(p)), None)
        if j is None:
            take(e)
            break
        p = pool.pop(j)
        selected[worst] = p
        take(p)
        n_in += 1
        replaced += 1
    selected.sort(key=key)
    if replaced:
        log("INFO", f"非英语配额：用 {replaced} 个非英语项目替换英语项目（要求 {need} 个）")
    if n_in < need:
        log("INFO", f"非英语合格候选只有 {n_in} 个，未达配额 {need} 个，不强行补足")
    return selected
