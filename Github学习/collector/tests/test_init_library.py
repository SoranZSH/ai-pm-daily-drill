"""v1.4：候选截断预留非英语名额、初始化模式、资料库。全部离线。"""
import datetime as dt
import glob
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import discover as dc  # noqa: E402
import library  # noqa: E402
from test_collect import D, Env, standard_repos  # noqa: E402

LONG_README = "# Demo\n\n## Architecture\n\n" + ("The system has a planner, a retriever with embedding and a vector database. " * 40)


def cand(i, stars, desc, channels=None):
    return {"repo_id": i, "full_name": f"o/r{i}", "name": f"r{i}", "description": desc,
            "stars": stars, "channels": channels or ["revival:topic:x"]}


class TruncateTest(unittest.TestCase):
    def test_non_english_reserved(self):
        en = [cand(i, 100000 - i, "A fast agent framework for building production assistants") for i in range(300)]
        zh = [cand(1000 + i, 100 + i, "一个用于构建智能体应用的开源框架，支持工具调用和长期记忆管理") for i in range(100)]
        cfg = {"max_candidates": 200, "languages": {"min_non_english_share": 0.3}}
        out = dc.truncate_candidates(en + zh, cfg)
        self.assertEqual(len(out), 200)
        self.assertEqual(sum(1 for c in out if c["repo_id"] >= 1000), 60)

    def test_keyword_channel_counts_as_non_english(self):
        en = [cand(i, 100000 - i, "Agent framework") for i in range(10)]
        kw = [cand(500, 5, "Agent framework", ["kw:ja:エージェント"])]
        cfg = {"max_candidates": 5, "languages": {"min_non_english_share": 0.3}}
        self.assertIn(500, [c["repo_id"] for c in dc.truncate_candidates(en + kw, cfg)])

    def test_keyword_query_uses_pushed(self):
        cfg = {"languages": {"keyword_min_stars": {"default": 50, "zh": 100}}}
        q = dc._range_query("kw:zh", "智能体", D(2026, 7, 1), None, cfg)
        self.assertEqual(q, "智能体 in:name,description,readme pushed:>=2026-07-01 stars:>=100")


class InitRunTest(Env):
    def setUp(self):
        super().setUp()
        repos = standard_repos()
        for full, r in repos.items():
            r["readmes"] = {"README.md": LONG_README}
            # 90 天窗口内持续增长
            r["daily"] = {D(2026, 7, 20) + dt.timedelta(days=k): 3 for k in range(70)}
        repos["own/d"]["readmes"] = {"README.md": "# tiny\n\nA list."}      # 太短，不收
        self.fake.repos = repos
        self.paths["library"] = os.path.join(self.tmp, "资料库")
        self.cfg["min_gain_window"] = 20

    def test_init_builds_large_pack_and_library(self):
        self.assertEqual(self.run_once(init=True, init_days=90, init_scale=5), 0)
        pk = self.pack()
        self.assertEqual(len(pk["run"]["star_days"]), 90)
        self.assertIn("初始化", pk["run"]["gap_note"])
        names = {p["full_name"] for p in pk["projects"]}
        self.assertEqual(names, {"own/a", "own/b", "own/c"})          # own/d README 过短
        lib = self.paths["library"]
        idx = json.load(open(os.path.join(lib, "index.json"), encoding="utf-8"))
        self.assertEqual(set(idx), names)
        self.assertTrue(os.path.exists(os.path.join(lib, "索引.md")))
        self.assertTrue(os.path.exists(os.path.join(lib, "README.md")))
        md = open(os.path.join(lib, "项目", "own__a.md"), encoding="utf-8").read()
        self.assertIn("只当资料使用", md)
        self.assertIn("Architecture", md)
        self.assertIn("rag.embedding", idx["own/a"]["concepts"])
        # 初始化后水位线推进到窗口终点，日常巡检从这里继续
        self.assertEqual(self.watermark(), "2026-10-10T03:00:00Z")

    def test_init_ignores_recent_success(self):
        self.assertEqual(self.run_once(), 0)                 # 普通运行
        before = len(self.packs())
        self.assertEqual(self.run_once(init=True), 0)        # 紧接着初始化：不受 20 小时限制、不受冷却期限制
        self.assertEqual(len(self.packs()), before + 1)
        self.assertGreaterEqual(len(self.pack()["projects"]), 3)


class LibraryTest(unittest.TestCase):
    def test_first_added_kept(self):
        import tempfile, shutil
        tmp = tempfile.mkdtemp()
        try:
            p = {"full_name": "a/b", "repo_id": 1, "description": "x", "direction": "rag", "domain": "RAG",
                 "doc_lang": "en", "stars": 10, "stars_gained_window": 5, "readme_sections": []}
            library.update(tmp, {"projects": [p]}, {}, "pack1.json", "2026-10-01")
            library.update(tmp, {"projects": [p]}, {}, "pack2.json", "2026-10-05")
            e = json.load(open(os.path.join(tmp, "index.json"), encoding="utf-8"))["a/b"]
            self.assertEqual((e["first_added"], e["last_updated"], e["packs"]),
                             ("2026-10-01", "2026-10-05", ["pack1.json", "pack2.json"]))
            self.assertEqual(len(glob.glob(os.path.join(tmp, "项目", "*.md"))), 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
