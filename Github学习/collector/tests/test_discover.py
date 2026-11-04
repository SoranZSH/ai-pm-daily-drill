"""第 3 步：discover.py 的单元测试（离线）。对应 M3 验收用例 6、7、8，并校验方向词表。"""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTOR = os.path.dirname(HERE)
sys.path.insert(0, COLLECTOR)

import discover as dc  # noqa: E402
import github_api as ga  # noqa: E402
import store  # noqa: E402

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 10, 3, 0, tzinfo=UTC)
D1 = dt.date(2026, 10, 7)
D2 = dt.date(2026, 10, 10)


def load_cfg():
    with open(os.path.join(COLLECTOR, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def item(rid, stars=10, fork=False, archived=False, name=None, desc="a repo"):
    name = name or f"r{rid}"
    return {"id": rid, "full_name": f"own/{name}", "name": name,
            "html_url": f"https://github.com/own/{name}", "description": desc,
            "topics": ["rag"], "language": "Python", "license": {"spdx_id": "MIT"},
            "created_at": "2026-10-01T00:00:00Z", "pushed_at": "2026-10-09T00:00:00Z",
            "stargazers_count": stars, "fork": fork, "archived": archived}


def parse_range(q):
    """从查询串中取日期区间：created:A..B 或 pushed:A..B；pushed:>=A 返回 (A, None)。"""
    import re
    m = re.search(r"(created|pushed):(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", q)
    if m:
        return dt.date.fromisoformat(m.group(2)), dt.date.fromisoformat(m.group(3))
    m = re.search(r"pushed:>=(\d{4}-\d{2}-\d{2})", q)
    return dt.date.fromisoformat(m.group(1)), None


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.st = store.Store(os.path.join(self.tmp, "state.db"))
        self.logs = []
        self.log = lambda lv, m: self.logs.append((lv, m))
        self.cfg = load_cfg()
        self.directions = {"x": {"topics": ["rag"]}}

    def tearDown(self):
        self.st.close()

    def api(self, handler):
        return ga.GitHubAPI(ga.FixtureTransport(handler=handler), "tok",
                            sleep=lambda s: None, mono=lambda: 0.0)


class SplitAndTruncateTest(Base):
    """用例 7：total_count 超过 1000 时拆分重查；单日仍超则记 truncated。"""

    def test_over_1000_is_split_and_merged(self):
        def handler(path, params):
            lo, hi = parse_range(params["q"])
            span = (hi - lo).days if hi else 99
            if span >= 1:
                return ga.Response(200, {}, {"total_count": 2500, "items": []})
            return ga.Response(200, {}, {"total_count": 3,
                                         "items": [item(int(lo.strftime("%Y%m%d")))]})

        cands, stats = dc.discover(self.api(handler), self.st, self.cfg, self.directions,
                                   D1, D2, NOW, self.log)
        self.assertGreater(stats["splits"], 0)
        self.assertEqual(stats["truncated"], 0)
        self.assertFalse(any("truncated" in m for _, m in self.logs))
        self.assertEqual(sorted(c["repo_id"] for c in cands),
                         [20261007, 20261008, 20261009, 20261010])

    def test_single_day_over_1000_logs_truncated(self):
        def handler(path, params):
            return ga.Response(200, {}, {"total_count": 1500, "items": [item(1)]})

        cands, stats = dc.discover(self.api(handler), self.st, self.cfg, self.directions,
                                   D2, D2, NOW, self.log)
        self.assertGreater(stats["truncated"], 0)
        self.assertTrue(any("truncated" in m for _, m in self.logs))
        self.assertEqual(len(cands), 1)


class MergeChannelsTest(Base):
    """用例 8：同一仓库被多个渠道发现，只出现一次，discovery_channels 包含全部标签。"""

    def test_one_row_many_channels(self):
        self.directions = {"a": {"topics": ["rag", "vector-search"]}}

        def handler(path, params):
            return ga.Response(200, {}, {"total_count": 1, "items": [item(5, stars=100)]})

        cands, _ = dc.discover(self.api(handler), self.st, self.cfg, self.directions,
                               D1, D2, NOW, self.log)
        self.assertEqual(len(cands), 1)
        self.assertEqual(sorted(cands[0]["channels"]), sorted([
            "new:topic:rag", "revival:topic:rag",
            "new:topic:vector-search", "revival:topic:vector-search"]))
        self.assertEqual(self.st.get_repo(5)["full_name"], "own/r5")


class FilterTest(Base):
    """用例 6：14 天内入包的仓库不再入包；超过冷却期的可以再入；已出题、fork、awesome 等被过滤。"""

    def test_cooldown_questioned_fork_awesome(self):
        now_iso = dc.fmt_iso(NOW)
        # 1：5 天前入包 → 冷却中，不入包
        self.st.upsert_repo(1, "own/r1", "u", now_iso)
        self.st.mark_packed(1, "run0", dc.fmt_iso(NOW - dt.timedelta(days=5)), 30, None)
        # 2：20 天前入包 → 冷却已过，可以入包
        self.st.upsert_repo(2, "own/r2", "u", now_iso)
        self.st.mark_packed(2, "run0", dc.fmt_iso(NOW - dt.timedelta(days=20)), 30, None)
        # 3：5 天前出题 → 未满 revisit_min_days（30 天），被过滤（M5.4 时间门槛）
        self.st.upsert_repo(3, "own/r3", "u", now_iso)
        self.st.set_repo_status(3, "questioned", None, "2026-10-05")
        # 7：39 天前出题 → 已满 30 天，进入复收考虑，发现阶段保留（是否入包由后续复收条件决定）
        self.st.upsert_repo(7, "own/r7", "u", now_iso)
        self.st.set_repo_status(7, "questioned", None, "2026-09-01")
        handler_items = [item(1, stars=50), item(2, stars=40), item(3, stars=30),
                         item(4, stars=20, fork=True), item(6, stars=10, name="awesome-rag"),
                         item(7, stars=15)]

        def handler(path, params):
            return ga.Response(200, {}, {"total_count": len(handler_items), "items": handler_items})

        cands, stats = dc.discover(self.api(handler), self.st, self.cfg, self.directions,
                                   D1, D2, NOW, self.log)
        self.assertEqual(sorted(c["repo_id"] for c in cands), [2, 7])
        self.assertEqual(self.st.get_repo(4)["status"], "skipped")
        self.assertEqual(self.st.get_repo(4)["status_reason"], "fork")
        self.assertEqual(self.st.get_repo(6)["status_reason"], "awesome")
        self.assertEqual(stats["dropped"].get("cooldown"), 1)
        self.assertEqual(stats["dropped"].get("questioned"), 1)

    def test_sorted_by_stars_and_max_candidates(self):
        self.cfg["max_candidates"] = 2
        items = [item(1, stars=10), item(2, stars=30), item(3, stars=20)]

        def handler(path, params):
            return ga.Response(200, {}, {"total_count": 3, "items": items})

        cands, _ = dc.discover(self.api(handler), self.st, self.cfg, self.directions,
                               D1, D2, NOW, self.log)
        self.assertEqual([c["stars"] for c in cands], [30, 20])


class QueryLogTest(Base):
    """第 9.7 节 (d)：每次搜索都记录 total_count（INFO），便于核对拆分是否正确。"""

    def test_each_query_logs_total_count(self):
        def handler(path, params):
            return ga.Response(200, {}, {"total_count": 3, "items": []})

        dc.discover(self.api(handler), self.st, self.cfg, self.directions, D1, D2, NOW, self.log)
        infos = [m for lv, m in self.logs if "total_count=3" in m]
        self.assertEqual(len(infos), 2)                     # 1 个主题 × 新建/复活 两条查询
        self.assertTrue(all(lv == "INFO" for lv, m in self.logs if "total_count" in m))


class DirectionFileTest(unittest.TestCase):
    """方向词表（v1.1：M3 建立，keywords 暂为空对象）。"""

    def test_directions_file_is_complete(self):
        d = dc.load_directions(os.path.join(COLLECTOR, "方向词表.json"))
        self.assertEqual(len(d), 19)
        for key, v in d.items():
            self.assertIn("domain", v, key)
            self.assertIsInstance(v["topics"], list, key)
            # M4：关键词按非英语语言分组，每种语言 0–3 个（拿不准的可以留空数组）
            self.assertTrue(set(v["keywords"]) <= {"zh", "ja", "ko", "ru", "es", "fr", "de", "pt"}, key)
            for lang, words in v["keywords"].items():
                self.assertTrue(0 <= len(words) <= 3, f"{key}/{lang}")
                self.assertTrue(all(isinstance(w, str) and w for w in words), f"{key}/{lang}")
        with open(os.path.join(COLLECTOR, "config.json"), encoding="utf-8") as f:
            enabled = set(json.load(f)["languages"]["enabled"]) - {"en"}
        covered = {lang for v in d.values() for lang in v["keywords"]}
        self.assertTrue(enabled <= covered, f"没有关键词的语言：{enabled - covered}")
        self.assertEqual(d["rag"]["keywords"]["zh"], ["检索增强", "RAG 知识库", "向量检索"])   # 协助决策 9.9 规则
        for lang in enabled:
            words = [w for v in d.values() for w in v["keywords"].get(lang, [])]
            self.assertEqual(len(words), len(set(words)), f"{lang} 有重复关键词")
        self.assertEqual(d["rag"]["prerequisites"],
                         ["rag.embedding", "rag.vector_db", "rag.chunking",
                          "rag.hybrid_rerank", "rag.retrieval_eval"])
        self.assertIn("rag", dc.all_topics(d))
        self.assertEqual(len(dc.all_topics(d)), len(set(dc.all_topics(d))))


if __name__ == "__main__":
    unittest.main()
