"""Star 历史（方案 M3.8）。

已确认的接口行为（用户 2026-10-10 实测，见 协助决策_M3开工前状态.md 第 9.6 节）：
- 时区：按 UTC 处理。week 时间戳都是 UTC 零点，且为周日。
- 换算：days[i] 对应 UTC 日期「week 所在日期 + i 天」，days 从周日开始。
- total 是当周 7 天之和，不是累计数。
- 最新一周可能包含尚未结束的今天；窗口终点当天的数字可能只是截至请求时的部分值。
  这是方案 M3.5 第 5 步「含两端」的已知效果，本模块不做额外处理。
- 分页：每页 30 周，最新在前；Link 头含 rel="next" 时还有更早的周。
- 不需要 Token 也能返回（未登录限额更低），正式运行仍使用 Token。
"""
from __future__ import annotations

import datetime as dt

import github_api as ga

HISTORY_PER_PAGE = 30
MAX_HISTORY_PAGES = 20   # 防止异常分页无限循环（20 页 ≈ 600 周）


class StarHistoryUnavailable(Exception):
    """接口 404/410：退化为快照差值估算（方案 M3.8）。"""


def _week_date(week_ts: int) -> dt.date:
    return dt.datetime.fromtimestamp(week_ts, tz=dt.timezone.utc).date()


def expand_weeks(weeks: list[dict]) -> dict[dt.date, int]:
    """把按周的数组展开成 {UTC 日期: 当日新增}。"""
    out: dict[dt.date, int] = {}
    for w in weeks:
        start = _week_date(int(w["week"]))
        for i, n in enumerate(w.get("days") or []):
            out[start + dt.timedelta(days=i)] = int(n)
    return out


def has_next_page(headers: dict) -> bool:
    link = headers.get("link", "")
    return 'rel="next"' in link


def fetch_history(api: ga.GitHubAPI, full_name: str, window_start: dt.date) -> dict[dt.date, int]:
    """取够覆盖窗口起点的所有周，返回 {UTC 日期: 当日新增}。"""
    path = f"/repos/{full_name}/stargazers/history"
    counts: dict[dt.date, int] = {}
    for page in range(1, MAX_HISTORY_PAGES + 1):
        r = api.get(path, {"per_page": HISTORY_PER_PAGE, "page": page})
        if r.status in (404, 410):
            raise StarHistoryUnavailable(f"HTTP {r.status}")
        if r.status != 200:
            raise ga.RequestFailed(f"{path}：HTTP {r.status}")
        weeks = r.body or []
        if not weeks:
            break
        counts.update(expand_weeks(weeks))
        earliest = _week_date(int(weeks[-1]["week"]))
        if earliest <= window_start or not has_next_page(r.headers):
            break
    return counts


def daily_for_window(counts: dict[dt.date, int], star_days: list[dt.date]) -> list[int]:
    return [int(counts.get(d, 0)) for d in star_days]


def gain_for_repo(api: ga.GitHubAPI, full_name: str, star_days: list[dt.date],
                  current_stars: int, snapshot_stars: int | None) -> dict:
    """返回 {daily, gain, estimated}。

    接口不可用时：用「当前 Star 数 − 上次快照」估算窗口新增，放在窗口最后一天，estimated=True。
    没有上次快照时无法估算，窗口新增记为 0。
    """
    if not star_days:
        return {"daily": [], "gain": 0, "estimated": False}
    try:
        counts = fetch_history(api, full_name, star_days[0])
    except StarHistoryUnavailable:
        n = len(star_days)
        if snapshot_stars is None:
            return {"daily": [0] * n, "gain": 0, "estimated": True}
        gain = max(0, int(current_stars) - int(snapshot_stars))
        return {"daily": [0] * (n - 1) + [gain], "gain": gain, "estimated": True}
    daily = daily_for_window(counts, star_days)
    return {"daily": daily, "gain": sum(daily), "estimated": False}
