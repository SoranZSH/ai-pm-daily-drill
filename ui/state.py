# -*- coding: utf-8 -*-
"""练习状态：与 daily.py 共用 data/history.json，另加提醒相关的 nudge 区块。

「今天学过没有」只看 history["study"]["days"]（练完一道题才写入），
弹窗出现、打开窗口又关掉都不算。
"""

import datetime as dt
import hashlib
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import daily  # noqa: E402


def today():
    """学习日（默认凌晨 4 点换日），不是日历上的日期。"""
    return daily.today_str()


def settings():
    return daily.settings()


def _key(day=None):
    return f"{day or today()}|all|1"      # 与 daily.py 的单题 key 一致


def load():
    h = daily.load_history()
    h.setdefault("nudge", {})
    n = h["nudge"]
    n.setdefault("done", [])              # 旧版字段，保留不再写入
    n.setdefault("snooze_active", 0)      # 旧版字段：计时现在存在 runtime.json，不再每分钟重写学习记录
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


# ── 运行状态（计时、暂停）：单独的小文件，和学习记录分开 ─────────────────────
def runtime_path():
    return os.path.join(daily.DATA_DIR, "runtime.json")


def runtime_load():
    try:
        with open(runtime_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def runtime_save(d):
    try:
        daily._atomic_write(runtime_path(), d)
    except OSError:
        pass


def runtime_update(**kw):
    d = runtime_load()
    d.update(kw)
    runtime_save(d)
    return d


# ── 今天的状态 ────────────────────────────────────────────────────────────
def done_today(h):
    """今天是否真正练完过一道题。"""
    return daily.studied_on(h)


def today_ids(h):
    """今天练完的题号（按完成顺序）。"""
    return daily.studied_ids_on(h)


def count_today(h):
    return len(today_ids(h))


def new_count_today(h):
    """今天练的题里有几道是第一次学（复习题不算）。"""
    srs = h.get("srs", {})
    return sum(1 for q in today_ids(h) if srs.get(q, {}).get("reps", 1) <= 1)


def skip_today(h, after_swap=False, qid=None):
    """今天不再提醒（不计入学习记录）。"""
    h["nudge"]["last_prompt"] = "skip:" + today()
    daily.log_event(h, "rest", after_swap=after_swap, id=qid)
    save(h)


def skipped_today(h):
    return h["nudge"]["last_prompt"] == "skip:" + today()


def stop_today(h, why="tired"):
    """今天学过了，到此为止：之后不再提醒下一题。"""
    h["nudge"]["last_prompt"] = "stop:" + today()
    daily.log_event(h, "stop", why=why, n=count_today(h))
    save(h)


def stopped_today(h):
    return h["nudge"]["last_prompt"] == "stop:" + today()


def snooze(h, seconds_needed_reset=True):
    """记下「今天提醒过了」。已经说了今天休息 / 今天到此为止的，保持原样。"""
    if skipped_today(h) or stopped_today(h):
        return
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
#   1. 今天练过的题今天不再出现（点了「没记住」的也是明天才回来）
#   2. 到期复习题优先；换题时不出复习题
#   3. 「已解锁」= 没练完过，且每道前置题要么已不在题库里，要么「记住了」并且不是今天才学的
#      —— 今天刚学的基础题，要等下一个学习日才解锁它后面的拓展题（贪多嚼不烂）
#   4. 新题候选池依次取：新鲜（已解锁且 added 在 fresh_days 天内）→ 已解锁
#   5. 每天第一题一定给得出（实在没有就退回：没练过的基础题 → 任意题）；
#      当天第二题起（strict）不凑数：受每日新题上限约束，没有合适的就返回 None
#   6. 池内用「日期 + 盐」作随机种子，保证同一天结果稳定
# 旧格式题目没有这些字段：按基础题、无前置、不新鲜处理。

FRESH_DAYS_DEFAULT = 21

# 当天没有下一题时的原因 → 界面上的说法
NO_MORE = {
    "blocked": "贪多嚼不烂，夯实基础下次继续",
    "cap": "今天的新题够了，剩下的明天继续",
    "max": "今天的量够了，明天见",
    "empty": "题库里的题都学过了，等新题上架",
    "tired": "学累了就歇着，明天见",
}


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


def _pools(items, h, exclude=()):
    """(到期复习题, 已解锁的新题, 没练过的题) —— 都已去掉今天练过的和 exclude。"""
    t = today()
    by_id = {i["id"]: i for i in items}
    seen_today = set(today_ids(h))
    skip = set(exclude) | seen_today
    done = daily.practiced_ids(h)
    srs = h.get("srs", {})
    # 记住了，而且不是今天才第一次学的（今天复习通过的老题照常算数）
    solid = {q for q in daily.mastered_ids(h)
             if q not in seen_today or srs.get(q, {}).get("reps", 0) >= 2}

    due = [by_id[k] for _, k in sorted(
        (v.get("due", ""), k) for k, v in srs.items()
        if v.get("due", "9999") <= t and k in by_id and k not in skip)]
    unseen = [i for i in items if i["id"] not in done and i["id"] not in skip]
    open_items = [i for i in unseen
                  if all(p in solid or p not in by_id for p in (i.get("prereq") or []))]
    return due, open_items, unseen


def _pick(items, h, exclude=(), salt="", strict=False):
    due, open_items, unseen = _pools(items, h, exclude)
    if due and (strict or not salt):       # 换题（非 strict 且带盐）时不给复习题，直接给新题
        return due[0]

    day, days = daily.logical_date(), fresh_days()
    skip = set(exclude) | set(today_ids(h))
    if strict:
        if new_count_today(h) >= settings()["new_per_day"]:
            return None
        pools = [[i for i in open_items if _is_fresh(i, day, days)], open_items]
    else:
        pools = [
            [i for i in open_items if _is_fresh(i, day, days)],
            open_items,
            [i for i in unseen if level_of(i) == "F"],
            [i for i in items if i["id"] not in skip],
            [i for i in items if i["id"] not in set(exclude)],
            items,
        ]
    pool = next((p for p in pools if p), None)
    if not pool:
        return None
    seed = int(hashlib.sha256((_key() + salt).encode()).hexdigest()[:12], 16)
    return random.Random(seed).choice(pool)


def why_no_more(h, items):
    """当天第二题起选不出题的原因：max / cap / blocked / empty（见 NO_MORE）。"""
    cfg = settings()
    if cfg["max_per_day"] and count_today(h) >= cfg["max_per_day"]:
        return "max"
    due, open_items, unseen = _pools(items, h)
    if open_items and new_count_today(h) >= cfg["new_per_day"]:
        return "cap"
    if unseen:                             # 还有没学的题，但都被前置题卡着
        return "blocked"
    return "empty"


def supply(h, items):
    """题库余量，给设置面板看。"""
    due, open_items, unseen = _pools(items, h)
    return {"total": len(items), "unseen": len(unseen), "open": len(open_items), "due": len(due)}


def prereq_titles(it, items, n=2):
    """拓展题的前置题（题号, 题目）列表，供界面显示。"""
    by_id = {i["id"]: i for i in items}
    out = []
    for p in (it.get("prereq") or [])[:n]:
        if p in by_id:
            out.append((p, by_id[p].get("q_cn", "")))
    return out


def today_question(h, items):
    """取今天的第一题；同一天里弹窗、练习窗口、命令行看到的是同一道。"""
    by_id = {i["id"]: i for i in items}
    got = [by_id[i] for i in h["drawn"].get(_key(), []) if i in by_id]
    if got:
        return got[0]
    it = _pick(items, h)
    h["drawn"][_key()] = [it["id"]]
    save(h)
    return it


def current_question(h, items, peek=False):
    """现在该练哪道题 → (题目, None)；今天没有可练的了 → (None, 原因)。

    今天第一题沿用 today_question；它练完之后按推荐顺序给下一题（到期复习 → 已解锁的新题），
    选中的题记在 nudge.current 里，保证弹窗预览和练习窗口是同一道。
    peek=True 只看不记（守护进程用来判断还要不要提醒）。"""
    by_id = {i["id"]: i for i in items}
    seen = set(today_ids(h))
    drawn = [i for i in h["drawn"].get(_key(), []) if i in by_id]
    if drawn and drawn[0] not in seen:
        return by_id[drawn[0]], None
    if not drawn and not seen:
        if peek:
            return _pick(items, h), None
        return today_question(h, items), None

    cur = h["nudge"].get("current") or {}
    if cur.get("day") == today() and cur.get("id") in by_id and cur["id"] not in seen:
        return by_id[cur["id"]], None

    cfg = settings()
    if cfg["max_per_day"] and len(seen) >= cfg["max_per_day"]:
        return None, "max"
    it = _pick(items, h, salt=f"|n{len(seen)}", strict=True)
    if it is None:
        return None, why_no_more(h, items)
    if not peek:
        h["nudge"]["current"] = {"day": today(), "id": it["id"]}
        save(h)
    return it, None


def is_review(h, it):
    """这道题以前练过（现在是到期复习）。"""
    return it["id"] in daily.practiced_ids(h)


def swap_today(h, items, current_id):
    """随机换一道（今天只能换一次）。换掉的题不算「抽到过」，以后还会出现。"""
    it = _pick(items, h, exclude={current_id}, salt="|swap")
    h["drawn"][_key()] = [it["id"]]
    h["nudge"]["swapped"] = today()
    daily.log_event(h, "swap", **{"from": current_id, "to": it["id"]})
    save(h)
    return it


def grade(h, qid, g, **meta):
    st = daily.schedule(h, qid, g, **meta)   # schedule 内部同时写学习记录
    save(h)
    return st
