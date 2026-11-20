#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日面试题 · 中英对照背诵工具
Daily Interview Question Trainer (CN/EN)

用法 Usage
----------
  python daily.py                 今天的题（先只显示题目，回车揭晓答案）
  python daily.py --show          直接连答案一起显示
  python daily.py -n 3            今天抽 3 道
  python daily.py -c data         只从某类抽题（见 --list-cats）
  python daily.py --list-cats     查看所有分类和题量
  python daily.py --id DA-007     指定题号查看
  python daily.py --search 漏斗    关键词搜索（中英文都搜）
  python daily.py --review        今天该复习的旧题（间隔重复 1/3/7/14/30 天）
  python daily.py --grade 4       给今天最后一道题打分 0-5（影响复习排期）
  python daily.py --stats         进度统计
  python daily.py --export-anki   导出 Anki CSV（out/anki.csv）
  python daily.py --export-md     导出全库 Markdown（out/全库.md）
  python daily.py --reset-today   重抽今天的题
"""

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import random
import re
import shutil
import sys
import time
import unicodedata

# Windows 控制台中文/UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
BANK_CONFIG = os.path.join(ROOT, "题库路径.json")


def bank_settings():
    """读取 题库路径.json 的全部设置（bank_dir、fresh_days 等）；读不到返回空字典。"""
    try:
        with open(BANK_CONFIG, encoding="utf-8-sig") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def resolve_bank_dir():
    """题库放在哪里由「题库路径.json」决定（{"bank_dir": "Github学习/当前题库"}，
    相对路径以本文件夹为准）。这是本程序与 Github学习 项目之间唯一的耦合点：
    对方只要保证那个文件夹里是符合格式的分类 JSON，本程序就能用。
    配置缺失或路径不存在时依次退回 Github学习/当前题库、bank/。"""
    cands = []
    p = bank_settings().get("bank_dir", "")
    if p:
        cands.append(p if os.path.isabs(p) else os.path.join(ROOT, p))
    cands += [os.path.join(ROOT, "Github学习", "当前题库"), os.path.join(ROOT, "bank")]
    for c in cands:
        if os.path.isdir(c):
            return os.path.normpath(c)
    return os.path.normpath(cands[0])


BANK_DIR = resolve_bank_dir()
DATA_DIR = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(ROOT, "out")
HISTORY = os.path.join(DATA_DIR, "history.json")
BACKUP_KEEP = 14       # 学习记录每天自动备份一份，保留最近这么多份


# ---------------------------------------------------------------- 设置
#
# data/settings.json 由设置面板写入；缺失或某一项不合法时用下面的默认值。
#   mode            single = 每天一题；multi = 当天学过之后继续按间隔提醒下一题
#   new_per_day     每天最多学几道新题（复习题不占名额）
#   max_per_day     每天最多练几道（新题 + 复习），0 = 不限
#   interval_min    点了「稍后」或学完一题后，再累计多少分钟活跃时间才提醒
#   retry_min       弹窗没人理自动收起后，多少分钟活跃时间后再试一次
#   warmup_min      每天第一次提醒前，至少先用多少分钟电脑
#   popup_secs      弹窗停留多少秒后自动收起
#   day_start_hour  学习日从几点开始（凌晨 4 点前的学习算前一天）

SETTINGS_DEFAULT = {
    "mode": "single",
    "new_per_day": 3,
    "max_per_day": 8,
    "interval_min": 60,
    "retry_min": 25,
    "warmup_min": 10,
    "popup_secs": 75,
    "day_start_hour": 4,
}
_SETTINGS_RANGE = {
    "new_per_day": (1, 50), "max_per_day": (0, 200), "interval_min": (5, 600),
    "retry_min": (5, 600), "warmup_min": (0, 240), "popup_secs": (15, 600),
    "day_start_hour": (0, 12),
}
_settings_cache = (None, None, None)       # (路径, (修改时间, 大小), 内容)


def settings_path():
    return os.path.join(DATA_DIR, "settings.json")


def settings():
    """读取设置（按文件的修改时间 + 大小缓存，守护进程每 15 秒调用一次也不费事）。
    只看修改时间不够：有的文件系统时间戳很粗，紧挨着的两次写入会落在同一个时间戳里。"""
    global _settings_cache
    path = settings_path()
    try:
        st = os.stat(path)
        mtime = (st.st_mtime_ns, st.st_size)
    except OSError:
        mtime = None
    if _settings_cache[0] == path and _settings_cache[1] == mtime:
        return dict(_settings_cache[2])
    out = dict(SETTINGS_DEFAULT)
    if mtime is not None:
        try:
            with open(path, encoding="utf-8-sig") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
        if isinstance(raw, dict):
            if raw.get("mode") in ("single", "multi"):
                out["mode"] = raw["mode"]
            for k, (lo, hi) in _SETTINGS_RANGE.items():
                v = raw.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi:
                    out[k] = int(v)
    _settings_cache = (path, mtime, out)
    return dict(out)


def save_settings(d):
    """只保存认识的键；不合法的值在读取时会被默认值替换。"""
    cur = settings()
    global _settings_cache
    cur.update({k: v for k, v in d.items() if k in SETTINGS_DEFAULT})
    _atomic_write(settings_path(), cur)
    _settings_cache = (None, None, None)       # 刚写过：下次一定重新读
    return settings()


def _atomic_write(path, obj):
    """先写临时文件再整体替换：写到一半断电或崩溃，原文件保持完好。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:            # Windows：目标文件正被别的程序读着，稍等再试
            time.sleep(0.05 * (attempt + 1))
    with open(path, "w", encoding="utf-8") as f:   # 实在换不了就退回直接写
        json.dump(obj, f, ensure_ascii=False, indent=2)
    try:
        os.remove(tmp)
    except OSError:
        pass

# 复习间隔（天）：答题评分越低，越早再见
INTERVALS = [1, 3, 7, 14, 30, 60]

W = 92  # 输出宽度


# ---------------------------------------------------------------- 加载 / 存储

def load_bank():
    items = []
    bank_dir = resolve_bank_dir()          # 每次现查：题库搬家后不用重启提醒程序
    if not os.path.isdir(bank_dir):
        sys.exit(f"找不到题库目录 {bank_dir}（检查 题库路径.json）")
    for fn in sorted(os.listdir(bank_dir)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(bank_dir, fn)
        with open(path, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                sys.exit(f"{fn} JSON 解析失败: {e}")
        for it in data.get("items", []):
            it.setdefault("category", data.get("category", "未分类"))
            it.setdefault("category_en", data.get("category_en", ""))
            it["_file"] = fn
            items.append(it)
    if not items:
        sys.exit("题库为空")
    return items


def backup_dir():
    return os.path.join(DATA_DIR, "backup")


def _backups():
    """现有备份文件，从新到旧。"""
    try:
        names = sorted((n for n in os.listdir(backup_dir())
                        if n.startswith("history_") and n.endswith(".json")), reverse=True)
    except OSError:
        return []
    return [os.path.join(backup_dir(), n) for n in names]


def load_history():
    if os.path.exists(HISTORY):
        try:
            with open(HISTORY, encoding="utf-8") as f:
                h = json.load(f)
        except ValueError:
            h = _restore_from_backup()
    else:
        h = {"drawn": {}, "srs": {}, "log": []}
    h.setdefault("drawn", {})
    h.setdefault("srs", {})
    h.setdefault("log", [])
    ensure_study(h)
    return h


def _restore_from_backup():
    """学习记录读不出来（文件损坏）：把坏文件改名留底，用最近一份能读的备份恢复。
    没有可用备份时原样报错，绝不拿空记录去覆盖。"""
    for path in _backups():
        try:
            with open(path, encoding="utf-8") as f:
                h = json.load(f)
        except (OSError, ValueError):
            continue
        bad = os.path.join(DATA_DIR, f"history.corrupt-{dt.datetime.now():%Y%m%d-%H%M%S}.json")
        shutil.copy2(HISTORY, bad)
        _atomic_write(HISTORY, h)
        return h
    with open(HISTORY, encoding="utf-8") as f:     # 重新触发原来的解析错误
        return json.load(f)


_backed_up = None       # 本进程今天是否已经检查过备份


def _backup_daily():
    """每个学习日第一次写入之前，把现有的学习记录复制一份到 data/backup/。"""
    global _backed_up
    day = today_str()
    if _backed_up == (HISTORY, day):
        return
    _backed_up = (HISTORY, day)
    try:
        if not os.path.exists(HISTORY) or os.path.getsize(HISTORY) == 0:
            return
        dst = os.path.join(backup_dir(), f"history_{day}.json")
        if os.path.exists(dst):
            return
        os.makedirs(backup_dir(), exist_ok=True)
        shutil.copy2(HISTORY, dst)
        for old in _backups()[BACKUP_KEEP:]:
            os.remove(old)
    except OSError:
        pass                # 备份失败不影响正常保存


def save_history(h):
    _backup_daily()
    _atomic_write(HISTORY, h)


# ---------------------------------------------------------------- 排版

def rule(char="─", label=""):
    if label:
        pad = max(0, W - len(label) - 4)
        return f"{char*2} {label} {char*pad}"
    return char * W


_TOK = re.compile(r"\s+|[\x21-\x7e]+|.")


def _cw(ch):
    """字符显示宽度：中日韩全角算 2 列。"""
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def wrap(text, indent=""):
    """中英混排换行：英文按词断，中文按字断，按显示宽度对齐。"""
    out = []
    for para in str(text).split("\n"):
        if not para.strip():
            out.append("")
            continue
        line, width = indent, len(indent)
        for tok in _TOK.findall(para):
            if tok.isspace():
                if width > len(indent):        # 行首不留空格
                    line, width = line + " ", width + 1
                continue
            tw = sum(_cw(c) for c in tok)
            if width + tw > W and width > len(indent):
                out.append(line.rstrip())
                line, width = indent, len(indent)
            line, width = line + tok, width + tw
        if line.strip():
            out.append(line.rstrip())
    return "\n".join(out)


def render_question(it, n=None, total=None):
    head = f"[{it['id']}] {it['category']} · {it.get('difficulty', '')}"
    if n and total:
        head = f"({n}/{total}) " + head
    print()
    print(rule("═"))
    print(head)
    if it.get("tags"):
        print("标签: " + " / ".join(it["tags"]))
    print(rule("═"))
    print()
    print(wrap("【中】" + it["q_cn"]))
    print()
    print(wrap("【EN】" + it["q_en"]))
    print()


def render_answer(it):
    if it.get("concept"):
        print(rule("─", "概念解析 What This Is (先搞懂再背)"))
        print()
        print(wrap(it["concept"]["cn"]))
        print()
        print(wrap(it["concept"]["en"]))
        print()
    print(rule("─", "参考答案 Model Answer (背这一段)"))
    print()
    print(wrap(it["a_en"]))
    print()
    print(rule("─", "中文对照"))
    print()
    print(wrap(it["a_cn"]))
    print()
    if it.get("key_phrases"):
        print(rule("─", "关键表达 Key Phrases"))
        for kp in it["key_phrases"]:
            print(f"  · {kp['en']}")
            print(f"      {kp['cn']}")
        print()
    if it.get("approach"):
        print(rule("─", "答题思路 How To Structure It"))
        print(wrap(it["approach"]))
        print()
    if it.get("tips"):
        print(rule("─", "答题提示 Tips"))
        print(wrap(it["tips"]))
        print()
    print(rule("═"))


# ---------------------------------------------------------------- 抽题逻辑

def logical_date(now=None):
    """学习日：默认凌晨 4 点才算新的一天，零点后接着学的仍算前一天。"""
    now = now or dt.datetime.now()
    return (now - dt.timedelta(hours=settings()["day_start_hour"])).date()


def today_str():
    return logical_date().isoformat()


def pick_today(items, hist, n, cat_filter, day=None):
    day = day or today_str()
    key = f"{day}|{cat_filter or 'all'}|{n}"
    if key in hist["drawn"]:
        by_id = {i["id"]: i for i in items}
        got = [by_id[i] for i in hist["drawn"][key] if i in by_id]
        if got:
            return got, False

    pool = items
    if cat_filter:
        cf = cat_filter.lower()
        pool = [i for i in items
                if cf in i["category"].lower()
                or cf in i.get("category_en", "").lower()
                or cf in i["id"].lower()]
        if not pool:
            sys.exit(f"没有匹配分类「{cat_filter}」的题，用 --list-cats 看可选值")

    # 已抽过的排在后面，保证抽完一轮再重复
    seen = set()
    for ids in hist["drawn"].values():
        seen.update(ids)
    fresh = [i for i in pool if i["id"] not in seen]
    if len(fresh) < n:
        fresh = fresh + [i for i in pool if i["id"] in seen]

    rng = random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:12], 16))
    chosen = rng.sample(fresh, min(n, len(fresh)))
    hist["drawn"][key] = [i["id"] for i in chosen]
    return chosen, True


def schedule(hist, qid, grade, **meta):
    """grade 0-5：>=3 前进一级，<3 退回第一级。
    打分 = 真正练完了一道题，所以这里同时记一笔学习记录。
    meta（用时 secs、是否开口计时 spoke、入口 mode 等）只写进行为日志，供以后统计。"""
    st = hist["srs"].get(qid, {"level": 0, "due": today_str(), "reps": 0})
    st["level"] = min(st["level"] + 1, len(INTERVALS) - 1) if grade >= 3 else 0
    st["reps"] = st.get("reps", 0) + 1
    st["last_grade"] = grade
    st["due"] = (logical_date() + dt.timedelta(days=INTERVALS[st["level"]])).isoformat()
    hist["srs"][qid] = st
    hist["log"].append({"date": today_str(), "id": qid, "grade": grade})
    record_study(hist, qid, grade, **meta)
    return st


# ---------------------------------------------------------------- 学习记录
#
# 只有「练完一道题」（看完答案并点了 完成 / 没记住，或命令行 --grade）才算当天学习过。
# 弹窗出现、打开练习窗口后直接关掉，都不算。
#
# history.json 里的结构：
#   "study": {
#     "days":   {"2026-10-09": ["RES-017"], ...},   学习日 → 当天练完的题
#     "events": [{"date", "type": "done"|"swap"|"rest", ...}, ...]   行为日志，供以后分析
#   }

def ensure_study(hist):
    """首次运行新版本时，从真实打分记录 log 重建学习日（旧版 nudge.done 记的是
    「打开过窗口」，不代表学过，所以不迁移它）。"""
    if "study" in hist:
        st = hist["study"]
        st.setdefault("days", {})
        st.setdefault("events", [])
        return st
    days = {}
    for e in hist.get("log", []):
        ids = days.setdefault(e["date"], [])
        if e["id"] not in ids:
            ids.append(e["id"])
    hist["study"] = {"days": days, "events": [], "migrated_from_log": today_str()}
    return hist["study"]


def record_study(hist, qid, grade=None, **meta):
    st = ensure_study(hist)
    ids = st["days"].setdefault(today_str(), [])
    if qid not in ids:
        ids.append(qid)
    log_event(hist, "done", id=qid, grade=grade, **meta)


def log_event(hist, kind, **kw):
    st = ensure_study(hist)
    ev = {"date": today_str(), "time": dt.datetime.now().strftime("%H:%M"), "type": kind}
    ev.update({k: v for k, v in kw.items() if v is not None})
    st["events"].append(ev)


def studied_on(hist, day=None):
    return (day or today_str()) in ensure_study(hist)["days"]


def study_stats(hist):
    """返回 (累计学习天数, 当前连续天数, 最长连续天数)。
    当前连续：今天还没学则从昨天往回数——今天还有机会续上，不算断。"""
    days = sorted(ensure_study(hist)["days"])
    if not days:
        return 0, 0, 0
    dates = [dt.date.fromisoformat(d) for d in days]

    longest = run = 1
    for a, b in zip(dates, dates[1:]):
        run = run + 1 if (b - a).days == 1 else 1
        longest = max(longest, run)

    done = set(days)
    d = logical_date()
    if d.isoformat() not in done:
        d -= dt.timedelta(days=1)
    current = 0
    while d.isoformat() in done:
        current += 1
        d -= dt.timedelta(days=1)
    return len(days), current, longest


def studied_ids_on(hist, day=None):
    """某个学习日练完的题号（按完成顺序）。"""
    return list(ensure_study(hist)["days"].get(day or today_str(), []))


def mastered_ids(hist):
    """最近一次打分是「记住了」（>=3 分）的题。拓展题要等前置题进了这里才解锁。"""
    out = set()
    for qid, v in hist.get("srs", {}).items():
        g = v.get("last_grade")
        if g is None:                      # 很早的记录没存分数：升过级就算记住
            g = 3 if v.get("level", 0) >= 1 else 0
        if g >= 3:
            out.add(qid)
    return out


def practiced_ids(hist):
    """真正练完过的题（不含只是被弹窗抽到过的）。"""
    ids = set(hist.get("srs", {}))
    for v in ensure_study(hist)["days"].values():
        ids.update(v)
    return ids


# ---------------------------------------------------------------- 命令

def cmd_list_cats(items):
    from collections import Counter
    c = Counter(i["category"] for i in items)
    print(f"\n共 {len(items)} 题\n")
    print(rule())
    for cat, n in sorted(c.items(), key=lambda x: -x[1]):
        sample = next(i for i in items if i["category"] == cat)
        prefix = sample["id"].split("-")[0]
        print(f"  {n:>4} 题   {prefix:<5}  {cat}   ({sample.get('category_en','')})")
    print(rule())
    print("  过滤示例: python daily.py -c DA   /   python daily.py -c 数据分析\n")


def cmd_stats(items, hist):
    drawn = practiced_ids(hist) & {i["id"] for i in items}   # 只数仍在题库里的题
    graded = hist["srs"]
    mastered = [k for k, v in graded.items() if v.get("level", 0) >= 3]
    due = [k for k, v in graded.items() if v.get("due", "9999") <= today_str()]
    print()
    print(rule("═", "进度 Progress"))
    print(f"  题库总量      {len(items)}")
    print(f"  已练完        {len(drawn)}  ({len(drawn)*100//len(items)}%)")
    print(f"  已打过分      {len(graded)}")
    print(f"  进入长间隔    {len(mastered)}")
    print(f"  今天待复习    {len(due)}")
    total, cur, best = study_stats(hist)
    print(f"  累计学习      {total} 天")
    print(f"  连续学习      {cur} 天")
    print(f"  最长连续      {best} 天")
    days = sorted(hist["study"]["days"])
    if days:
        print(f"  最近一次      {days[-1]}")
    print(rule("═"))
    print()


def cmd_review(items, hist, show):
    by_id = {i["id"]: i for i in items}
    due = sorted([(v.get("due", ""), k) for k, v in hist["srs"].items()
                  if v.get("due", "9999") <= today_str() and k in by_id])
    if not due:
        print("\n今天没有到期的复习题。先做新题：python daily.py\n")
        return
    print(f"\n今天有 {len(due)} 道到期复习：\n")
    for n, (_, qid) in enumerate(due, 1):
        it = by_id[qid]
        render_question(it, n, len(due))
        if not show:
            try:
                input("  [回车] 揭晓答案 …")
            except EOFError:
                pass
        render_answer(it)


def cmd_export_anki(items):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "anki.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        for it in items:
            front = f"[{it['id']}] {it['q_en']}<br><br><i>{it['q_cn']}</i>"
            kp = "<br>".join(f"{k['en']} — {k['cn']}" for k in it.get("key_phrases", []))
            con = it.get("concept")
            back = ""
            if con:
                back += f"<b>概念</b><br>{con['cn']}<br><i>{con['en']}</i><br><br><hr>"
            back += f"{it['a_en']}<br><br><hr>{it['a_cn']}"
            if kp:
                back += f"<br><br><hr><b>Key phrases</b><br>{kp}"
            if it.get("approach"):
                back += f"<br><br><hr><b>思路</b><br>{it['approach']}"
            w.writerow([front, back, it["category"]])
    print(f"已导出 {len(items)} 张卡片 -> {path}")
    print("Anki 导入时选「字段以逗号分隔」，三个字段依次为 正面/背面/标签。")


def cmd_export_md(items):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "全库.md")
    from collections import defaultdict
    groups = defaultdict(list)
    for it in items:
        groups[it["category"]].append(it)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# 面试英语题库（{len(items)} 题）\n\n")
        for cat in groups:
            f.write(f"- [{cat}](#{cat.replace(' ', '-')}) — {len(groups[cat])} 题\n")
        for cat, its in groups.items():
            f.write(f"\n\n---\n\n## {cat}\n")
            for it in its:
                f.write(f"\n### {it['id']} · {it['q_cn']}\n\n")
                f.write(f"**EN.** {it['q_en']}\n\n")
                if it.get("concept"):
                    f.write(f"**概念解析.** {it['concept']['cn']}\n\n")
                    f.write(f"*{it['concept']['en']}*\n\n")
                f.write(f"> {it['a_en']}\n\n")
                f.write(f"**中文对照.** {it['a_cn']}\n\n")
                if it.get("key_phrases"):
                    f.write("**Key phrases:** "
                            + "; ".join(f"`{k['en']}` {k['cn']}"
                                        for k in it["key_phrases"]) + "\n\n")
                if it.get("approach"):
                    f.write(f"**答题思路.** {it['approach']}\n\n")
                if it.get("tips"):
                    f.write(f"**Tips.** {it['tips']}\n\n")
    print(f"已导出 -> {path}")


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(add_help=True, description="每日面试题 · 中英对照背诵")
    p.add_argument("-n", type=int, default=1, help="今天抽几道（默认 1）")
    p.add_argument("-c", "--cat", help="限定分类，如 DA / 数据分析")
    p.add_argument("--show", action="store_true", help="直接显示答案，不等回车")
    p.add_argument("--id", help="指定题号")
    p.add_argument("--search", help="关键词搜索")
    p.add_argument("--review", action="store_true", help="复习到期题")
    p.add_argument("--grade", type=int, choices=range(6), help="给今天的题打分 0-5")
    p.add_argument("--stats", action="store_true")
    p.add_argument("--list-cats", action="store_true")
    p.add_argument("--export-anki", action="store_true")
    p.add_argument("--export-md", action="store_true")
    p.add_argument("--reset-today", action="store_true", help="重抽今天的题")
    a = p.parse_args()

    items = load_bank()
    hist = load_history()
    by_id = {i["id"]: i for i in items}

    if a.list_cats:
        return cmd_list_cats(items)
    if a.stats:
        return cmd_stats(items, hist)
    if a.export_anki:
        return cmd_export_anki(items)
    if a.export_md:
        return cmd_export_md(items)

    if a.reset_today:
        today = today_str()
        for k in [k for k in hist["drawn"] if k.startswith(today)]:
            del hist["drawn"][k]
        save_history(hist)
        print("今天的抽题记录已清空，重新运行 python daily.py")
        return

    if a.grade is not None:
        last = hist.get("last_shown")
        if not last:
            print("还没抽过题，先运行 python daily.py")
            return
        st = schedule(hist, last, a.grade)
        save_history(hist)
        print(f"{last} 记为 {a.grade} 分，下次复习 {st['due']}")
        return

    if a.review:
        return cmd_review(items, hist, a.show)

    if a.id:
        it = by_id.get(a.id.upper())
        if not it:
            sys.exit(f"没有题号 {a.id}")
        render_question(it)
        render_answer(it)
        hist["last_shown"] = it["id"]
        save_history(hist)
        return

    if a.search:
        kw = a.search.lower()
        hits = [i for i in items if kw in json.dumps(i, ensure_ascii=False).lower()]
        print(f"\n命中 {len(hits)} 题：\n")
        for i in hits[:60]:
            print(f"  {i['id']:<9} {i['category']:<12} {i['q_cn'][:46]}")
        print(f"\n看详情: python daily.py --id {hits[0]['id']}\n" if hits else "")
        return

    chosen, is_new = pick_today(items, hist, a.n, a.cat)
    save_history(hist)
    print(f"\n{today_str()} · 今日题目 {len(chosen)} 道"
          + ("" if is_new else "（今天已抽过，重放；要换题用 --reset-today）"))
    for n, it in enumerate(chosen, 1):
        render_question(it, n, len(chosen))
        if not a.show:
            print("  先自己用英文说一遍（60-90 秒），再看参考答案。")
            try:
                input("  [回车] 揭晓 …")
            except EOFError:
                pass
        render_answer(it)
    hist["last_shown"] = chosen[-1]["id"]
    save_history(hist)
    print("\n背完给自己打分（0-5，影响复习排期）:  python daily.py --grade 4\n")


if __name__ == "__main__":
    main()
