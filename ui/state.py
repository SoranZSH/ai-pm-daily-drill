# -*- coding: utf-8 -*-
"""练习状态：与 daily.py 共用 data/history.json，另加提醒相关的 nudge 区块。

「今天学过没有」只看 history["study"]["days"]（练完一道题才写入），
弹窗出现、打开窗口又关掉都不算。
"""

import datetime as dt
import hashlib
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import daily  # noqa: E402


def today():
    return dt.date.today().isoformat()


def _key(day=None):
    return f"{day or today()}|all|1"      # 与 daily.py 的单题 key 一致


def load():
    h = daily.load_history()
    h.setdefault("nudge", {})
    n = h["nudge"]
    n.setdefault("done", [])              # 旧版字段，保留不再写入
    n.setdefault("snooze_active", 0)
    n.setdefault("last_prompt", "")
    n.setdefault("swapped", "")           # 今天是否已换过题（存日期）
    return h


def save(h):
    daily.save_history(h)


def bank():
    return daily.load_bank()


def total():
    """题库总量（每次现读，题库更新后不用重启也能显示对）。"""
    try:
        return len(daily.load_bank())
    except SystemExit:
        return 0


# ── 今天的状态 ────────────────────────────────────────────────────────────
def done_today(h):
    """今天是否真正练完过一道题。"""
    return daily.studied_on(h)


def skip_today(h, after_swap=False, qid=None):
    """今天不再提醒（不计入学习记录）。"""
    h["nudge"]["last_prompt"] = "skip:" + today()
    daily.log_event(h, "rest", after_swap=after_swap, id=qid)
    save(h)


def skipped_today(h):
    return h["nudge"]["last_prompt"] == "skip:" + today()


def snooze(h, seconds_needed_reset=True):
    if seconds_needed_reset:
        h["nudge"]["snooze_active"] = 0
    h["nudge"]["last_prompt"] = today()
    save(h)


def swapped_today(h):
    return h["nudge"].get("swapped") == today()


# ── 进度 ──────────────────────────────────────────────────────────────────
def stats(h):
    """(累计学习天数, 当前连续天数, 最长连续天数)"""
    return daily.study_stats(h)


def streak(h):
    return stats(h)[1]


def seen_count(h):
    """真正练完过、且仍在当前题库里的题数（题库覆盖后旧题不再计入）。"""
    try:
        ids = {i["id"] for i in daily.load_bank()}
    except SystemExit:
        return 0
    return len(daily.practiced_ids(h) & ids)


def due_count(h):
    t = today()
    return sum(1 for v in h.get("srs", {}).values() if v.get("due", "9999") <= t)


# ── 选题 ──────────────────────────────────────────────────────────────────
#
# 题库 v2 的题目带 level（F 基础 / X 拓展）、prereq（前置题号）、added（导入日期）。
# 规则：
#   1. 到期复习题优先（「没记住的明天再出现」）；换题时不出复习题
#   2. 「已解锁」= 没练完过，且每道前置题要么练完过、要么已不在题库里
#   3. 候选池依次取：新鲜（已解锁且 added 在 fresh_days 天内）→ 已解锁 → 没练过的基础题 → 全部
#   4. 池内用「日期 + 盐」作随机种子，保证同一天结果稳定
# 旧格式题目没有这些字段：按基础题、无前置、不新鲜处理。

FRESH_DAYS_DEFAULT = 21


def fresh_days():
    try:
        return max(0, int(daily.bank_settings().get("fresh_days", FRESH_DAYS_DEFAULT)))
    except (TypeError, ValueError):
        return FRESH_DAYS_DEFAULT


def level_of(it):
    return it.get("level") or "F"


def _is_fresh(it, day, days):
    try:
        added = dt.date.fromisoformat(str(it.get("added", ""))[:10])
    except ValueError:
        return False
    return 0 <= (day - added).days <= days


def _pick(items, h, exclude=(), salt=""):
    t = today()
    exclude = set(exclude)
    by_id = {i["id"]: i for i in items}

    due = sorted((v.get("due", ""), k) for k, v in h.get("srs", {}).items()
                 if v.get("due", "9999") <= t and k in by_id and k not in exclude)
    if due and not salt:                   # 换题时不再给复习题，直接给新题
        return by_id[due[0][1]]

    done = daily.practiced_ids(h)

    def unlocked(it):
        return (it["id"] not in done and it["id"] not in exclude
                and all(p in done or p not in by_id for p in (it.get("prereq") or [])))

    day, days = dt.date.today(), fresh_days()
    open_items = [i for i in items if unlocked(i)]
    pools = [
        [i for i in open_items if _is_fresh(i, day, days)],
        open_items,
        [i for i in items if i["id"] not in done and i["id"] not in exclude and level_of(i) == "F"],
        [i for i in items if i["id"] not in exclude],
        items,
    ]
    pool = next(p for p in pools if p)
    seed = int(hashlib.sha256((_key() + salt).encode()).hexdigest()[:12], 16)
    return random.Random(seed).choice(pool)


def prereq_titles(it, items, n=2):
    """拓展题的前置题（题号, 题目）列表，供界面显示。"""
    by_id = {i["id"]: i for i in items}
    out = []
    for p in (it.get("prereq") or [])[:n]:
        if p in by_id:
            out.append((p, by_id[p].get("q_cn", "")))
    return out


def today_question(h, items):
    """取今天的题；同一天里弹窗、练习窗口、命令行看到的是同一道。"""
    by_id = {i["id"]: i for i in items}
    got = [by_id[i] for i in h["drawn"].get(_key(), []) if i in by_id]
    if got:
        return got[0]
    it = _pick(items, h)
    h["drawn"][_key()] = [it["id"]]
    save(h)
    return it


def swap_today(h, items, current_id):
    """随机换一道（今天只能换一次）。换掉的题不算「抽到过」，以后还会出现。"""
    it = _pick(items, h, exclude={current_id}, salt="|swap")
    h["drawn"][_key()] = [it["id"]]
    h["nudge"]["swapped"] = today()
    daily.log_event(h, "swap", **{"from": current_id, "to": it["id"]})
    save(h)
    return it


def grade(h, qid, g):
    st = daily.schedule(h, qid, g)        # schedule 内部同时写学习记录
    save(h)
    return st
