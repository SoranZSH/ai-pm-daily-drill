"""第 3 步（M4.2）：关键词发现的离线测试。对应 M4 验收用例 6（每语言每次 12 个，超出从断点继续）。"""
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

D1 = dt.date(2026, 10, 7)
D2 = dt.date(2026, 10, 10)
NON_EN = {"zh", "ja", "ko", "ru", "es", "fr", "de", "pt"}


def load_cfg():
    with open(os.path.join(COLLECTOR, "config.json"), encoding="utf-8") as f:
        return json.load(f)


class QueueTest(unittest.TestCase):
    def test_round_robin_across_directions(self):
        d = {"a": {"keywords": {"zh": ["甲1", "甲2"]}},
             "b": {"keywords": {"zh": ["乙1"]}},
             "c": {"keywords": {"zh": ["丙1", "丙2", "丙3"]}}}
        self.assertEqual(dc.keyword_pairs(d, "zh"),
                         [("a", "甲1"), ("b", "乙1"), ("c", "丙1"), ("a", "甲2"), ("c", "丙2"), ("c", "丙3")])

    def test_pick_twelve_then_continue_from_thirteenth(self):
        # 验收用例 6：队列 30 个；第一次执行前 12 个，第二次从第 13 个开始
        pairs = [("x", f"k{i}") for i in range(30)]
        picked, nxt = dc.pick_keyword_queries(pairs, 0, 12)
        self.assertEqual([k for _, k in picked], [f"k{i}" for i in range(12)])
        self.assertEqual(nxt, 12)
        picked, nxt = dc.pick_keyword_queries(pairs, nxt, 12)
        self.assertEqual([k for _, k in picked], [f"k{i}" for i in range(12, 24)])
        self.assertEqual(nxt, 24)

    def test_pick_wraps_around_end_of_queue(self):
        pairs = [("x", f"k{i}") for i in range(30)]
        picked, nxt = dc.pick_keyword_queries(pairs, 24, 12)
        self.assertEqual([k for _, k in picked][-2:], ["k4", "k5"])     # 24..29 之后回绕到 0..5
        self.assertEqual(len(picked), 12)
        self.assertEqual(picked[6], ("x", "k0"))                  # 第 25 个之后回绕到第 1 个
        self.assertEqual(nxt, 6)

    def test_empty_queue(self):
        self.assertEqual(dc.pick_keyword_queries([], 5, 12), ([], 0))


class QueryFormatTest(unittest.TestCase):
    def test_keyword_query_uses_created_range_and_language_min_stars(self):
        cfg = load_cfg()
        self.assertEqual(dc._range_query("kw:zh", "检索增强", D1, D2, cfg),
                         "检索增强 in:name,description,readme pushed:2026-10-07..2026-10-10 stars:>=20")
        self.assertEqual(dc._range_query("kw:ko", "검색", D1, D2, cfg),
                         "검색 in:name,description,readme pushed:2026-10-07..2026-10-10 stars:>=10")
        self.assertEqual(dc._range_query("kw:fr", "génération", D1, D2, cfg),
                         "génération in:name,description,readme pushed:2026-10-07..2026-10-10 stars:>=15")


    def test_multi_word_keyword_is_quoted_as_phrase(self):
        # 协助决策 9.9 第 6 条：含空格的关键词按短语匹配，否则 GitHub 会把它拆成多个词
        cfg = load_cfg()
        self.assertEqual(dc._range_query("kw:zh", "RAG 知识库", D1, D2, cfg),
                         '"RAG 知识库" in:name,description,readme pushed:2026-10-07..2026-10-10 stars:>=20')
        self.assertEqual(dc._range_query("kw:zh", "检索增强", D1, D2, cfg),
                         "检索增强 in:name,description,readme pushed:2026-10-07..2026-10-10 stars:>=20")


class KeywordDiscoverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.st = store.Store(os.path.join(self.tmp, "state.db"))
        self.cfg = load_cfg()
        self.queries = []
        self.logs = []
        self.log = lambda lv, m: self.logs.append(m)
        self.directions = {"x": {"topics": [], "keywords": {"zh": [f"k{i}" for i in range(30)]}}}

    def tearDown(self):
        self.st.close()

    def handler(self, path, params):
        if path == "/search/repositories":
            self.queries.append(params["q"])
        return ga.Response(200, {}, {"total_count": 0, "items": []})

    def api(self):
        return ga.GitHubAPI(ga.FixtureTransport(handler=self.handler), "tok",
                            sleep=lambda s: None, mono=lambda: 0.0)

    def run_discover(self):
        self.queries.clear()
        cands, stats = dc.discover(self.api(), self.st, self.cfg, self.directions, D1, D2,
                                   dt.datetime(2026, 10, 10, 3, tzinfo=dt.timezone.utc), self.log)
        return cands, stats

    def test_only_non_english_enabled_languages_and_limit_twelve(self):
        _, stats = self.run_discover()
        kw_queries = [q for q in self.queries if " in:name,description,readme " in q]
        self.assertEqual(len(kw_queries), 12)
        self.assertEqual(stats["rotation"], {"zh": 12})            # 其他语言没有关键词，不出现
        self.assertTrue(all(q.startswith("k") for q in kw_queries))
        self.assertEqual(set(self.cfg["languages"]["enabled"]) - {"en"}, NON_EN)   # 只对非英语语言发现

    def test_second_run_continues_from_saved_pointer(self):
        self.st.meta_set_json("kw_rotation_zh", {"pos": 12})     # 上次成功运行保存的断点
        _, stats = self.run_discover()
        kw_queries = [q for q in self.queries if " in:name,description,readme " in q]
        self.assertEqual([q.split(" ")[0] for q in kw_queries], [f"k{i}" for i in range(12, 24)])
        self.assertEqual(stats["rotation"]["zh"], 24)
        # 断点由 discover 只返回、不写入：调用方（collect.py）在出包成功后才保存
        self.assertEqual(self.st.meta_get_json("kw_rotation_zh")["pos"], 12)

    def test_keyword_hits_carry_channel_label(self):
        self.handler_items = [{"id": 77, "full_name": "own/kw", "name": "kw", "html_url": "u",
                               "description": "d", "topics": [], "language": "Python", "license": None,
                               "created_at": "", "pushed_at": "", "stargazers_count": 40,
                               "fork": False, "archived": False}]

        def handler(path, params):
            if path == "/search/repositories" and params["q"].startswith("k0 "):
                return ga.Response(200, {}, {"total_count": 1, "items": self.handler_items})
            return ga.Response(200, {}, {"total_count": 0, "items": []})

        self.handler = handler
        cands, _ = self.run_discover()
        self.assertEqual(len(cands), 1)
        self.assertIn("kw:zh:k0", cands[0]["channels"])


if __name__ == "__main__":
    unittest.main()
