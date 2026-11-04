"""第 5 步：stars.py 的单元测试（离线）。对应 M3 验收用例 9，并覆盖分页与退化估算。"""
import datetime as dt
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTOR = os.path.dirname(HERE)
sys.path.insert(0, COLLECTOR)

import github_api as ga  # noqa: E402
import stars as st  # noqa: E402

UTC = dt.timezone.utc
REAL = os.path.join(HERE, "fixtures", "stargazers_history_real_psf_requests.json")


def week_ts(d: dt.date) -> int:
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())


def days_range(a: dt.date, b: dt.date):
    return [a + dt.timedelta(days=i) for i in range((b - a).days + 1)]


class RealFixtureTest(unittest.TestCase):
    """用例 9：用真实接口返回手算窗口新增，与程序结果一致。"""

    def setUp(self):
        with open(REAL, encoding="utf-8") as f:
            self.real = json.load(f)

    def api(self):
        return ga.GitHubAPI(ga.FixtureTransport(handler=lambda p, q: ga.Response(200, {}, self.real)),
                            "tok", sleep=lambda s: None)

    def test_expand_real_week_maps_sunday_first(self):
        counts = st.expand_weeks(self.real)
        # 2026-10-04 是周日（UTC 零点）：days[0] = 36
        self.assertEqual(counts[dt.date(2026, 10, 4)], 36)
        self.assertEqual(counts[dt.date(2026, 10, 10)], 0)     # 当前周的周六（部分值）
        self.assertEqual(counts[dt.date(2026, 9, 27)], 8)

    def test_window_oct1_to_oct4_matches_hand_calculation(self):
        # 手算：10-01=6，10-02=0，10-03=50，10-04=36 → 92
        r = st.gain_for_repo(self.api(), "psf/requests", days_range(dt.date(2026, 10, 1), dt.date(2026, 10, 4)),
                             current_stars=0, snapshot_stars=None)
        self.assertEqual(r["daily"], [6, 0, 50, 36])
        self.assertEqual(r["gain"], 92)
        self.assertFalse(r["estimated"])

    def test_window_crossing_two_weeks_matches_hand_calculation(self):
        # 手算：09-27..10-04 = 8+3+12+7+6+0+50+36 = 122
        r = st.gain_for_repo(self.api(), "psf/requests", days_range(dt.date(2026, 9, 27), dt.date(2026, 10, 4)),
                             current_stars=0, snapshot_stars=None)
        self.assertEqual(r["gain"], 122)
        self.assertEqual(len(r["daily"]), 8)


class PaginationTest(unittest.TestCase):
    def test_second_page_fetched_only_when_window_older_than_first_page(self):
        page1 = [{"week": week_ts(dt.date(2026, 9, 27)), "total": 1, "days": [1, 0, 0, 0, 0, 0, 0]},
                 {"week": week_ts(dt.date(2026, 9, 20)), "total": 1, "days": [0, 0, 0, 0, 0, 0, 0]}]
        page2 = [{"week": week_ts(dt.date(2026, 9, 13)), "total": 4, "days": [0, 0, 0, 0, 4, 0, 0]}]

        def handler(path, params):
            if params["page"] == 1:
                return ga.Response(200, {"link": '<x>; rel="next", <y>; rel="last"'}, page1)
            return ga.Response(200, {}, page2)

        t = ga.FixtureTransport(handler=handler)
        api = ga.GitHubAPI(t, "tok", sleep=lambda s: None)
        # 窗口起点 9-14 早于第一页最早一周（9-20）→ 需要第 2 页
        counts = st.fetch_history(api, "o/r", dt.date(2026, 9, 14))
        self.assertEqual(len(t.calls), 2)
        self.assertEqual(counts[dt.date(2026, 9, 17)], 4)      # 9-13 周的周四
        # 窗口起点已被第一页覆盖 → 只请求一页
        t2 = ga.FixtureTransport(handler=handler)
        api2 = ga.GitHubAPI(t2, "tok", sleep=lambda s: None)
        st.fetch_history(api2, "o/r", dt.date(2026, 9, 25))
        self.assertEqual(len(t2.calls), 1)


class FallbackTest(unittest.TestCase):
    """接口 404/410 时退化为快照差值估算（方案 M3.8）。"""

    def api_404(self):
        return ga.GitHubAPI(ga.FixtureTransport(handler=lambda p, q: ga.Response(404, {}, None)),
                            "tok", sleep=lambda s: None)

    def test_estimate_from_snapshot(self):
        r = st.gain_for_repo(self.api_404(), "o/r", days_range(dt.date(2026, 10, 7), dt.date(2026, 10, 10)),
                             current_stars=55, snapshot_stars=40)
        self.assertTrue(r["estimated"])
        self.assertEqual(r["gain"], 15)
        self.assertEqual(r["daily"], [0, 0, 0, 15])

    def test_no_snapshot_means_zero_estimate(self):
        r = st.gain_for_repo(self.api_404(), "o/r", days_range(dt.date(2026, 10, 7), dt.date(2026, 10, 10)),
                             current_stars=55, snapshot_stars=None)
        self.assertTrue(r["estimated"])
        self.assertEqual(r["gain"], 0)

    def test_server_error_is_not_silently_estimated(self):
        api = ga.GitHubAPI(ga.FixtureTransport(handler=lambda p, q: ga.Response(403, {}, None)),
                           "tok", sleep=lambda s: None)
        with self.assertRaises(ga.RequestFailed):
            st.gain_for_repo(api, "o/r", days_range(dt.date(2026, 10, 7), dt.date(2026, 10, 10)),
                             current_stars=1, snapshot_stars=None)


if __name__ == "__main__":
    unittest.main()
