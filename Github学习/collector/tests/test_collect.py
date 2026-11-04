"""第 6 步：collect.py 主流程的运行级测试（离线夹具）。

对应 M3 验收用例 1、2、3、4、5、12、13、14；用例 6、7、8 的单元测试在 test_discover.py。
所有运行都使用临时目录，绝不触碰真实的 state.db、采集包或采集日志。
"""
import base64
import datetime as dt
import glob
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTOR = os.path.dirname(HERE)
sys.path.insert(0, COLLECTOR)

import collect as col  # noqa: E402
import github_api as ga  # noqa: E402
import store as stmod  # noqa: E402

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 10, 3, 27, tzinfo=UTC)          # 窗口终点 03:00 UTC
TOKEN = "ghp_TESTTOKEN_0123456789abcdef"

PROJECT_KEYS = {
    "repo_id", "full_name", "html_url", "description", "topics", "language", "license",
    "created_at", "pushed_at", "stars", "stars_gained_window", "stars_daily", "heat_score",
    "doc_lang", "doc_lang_confidence", "doc_langs_available", "lang_group",
    "discovery_channels", "direction", "direction_confidence", "secondary_directions",
    "domain", "learning_mode", "mode_reason", "prerequisites_missing", "related_questions",
    "diff_evidence", "readme_sections", "readme_en_sections", "arch_docs", "papers",
    "latest_release", "tree_top2", "dependencies", "languages", "untrusted_content",
}
D = dt.date

# 测试用知识地图（概念键 → 名称、领域、别名）
CONCEPTS = {
    "rag.embedding": {"name": "向量嵌入", "domain": "RAG", "aliases": ["embedding", "向量嵌入"]},
    "rag.vector_db": {"name": "向量数据库", "domain": "RAG", "aliases": ["vector database", "向量数据库"]},
    "rag.chunking": {"name": "文本切块", "domain": "RAG", "aliases": ["chunking", "文本切块"]},
    "rag.hybrid_rerank": {"name": "混合检索与重排序", "domain": "RAG", "aliases": ["rerank", "重排序"]},
    "rag.retrieval_eval": {"name": "检索评测", "domain": "RAG", "aliases": ["retrieval evaluation", "检索评测"]},
}


def ts(d: dt.date) -> int:
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())


def weeks_for(daily: dict) -> list:
    """按周的 Star 历史（最新在前），覆盖 2026-07-05 至 2026-10-04 的周日。"""
    out = []
    d = D(2026, 7, 5)
    while d <= D(2026, 10, 4):
        days = [daily.get(d + dt.timedelta(days=i), 0) for i in range(7)]
        out.append({"week": ts(d), "total": sum(days), "days": days})
        d += dt.timedelta(days=7)
    return list(reversed(out))


class FakeGitHub:
    """离线 GitHub：仓库数据来自 repos 字典。fail_paths 中的路径抛网络错误。"""

    def __init__(self, repos: dict):
        self.repos = repos
        self.fail_paths: set = set()
        self.preflight_error = None
        self.history_status = 200           # 设为 404 可模拟 Star 历史接口不可用
        self.status_override: dict = {}     # {路径: HTTP 状态码}：模拟单个项目的非网络错误（如 422）
        self.calls: list = []

    def meta(self, full, r):
        return {"id": r["id"], "full_name": full, "html_url": f"https://github.com/{full}",
                "name": full.split("/")[1], "description": r.get("desc", f"{full} description"),
                "topics": ["rag"], "language": "Python", "license": {"spdx_id": "MIT"},
                "created_at": "2026-01-01T00:00:00Z", "pushed_at": "2026-10-09T00:00:00Z",
                "stargazers_count": r["stars"], "fork": False, "archived": False,
                "default_branch": "main"}

    def __call__(self, path, params):
        self.calls.append(path)
        if path in self.status_override:
            return ga.Response(self.status_override[path], {}, None)
        if path in self.fail_paths:
            raise ga.TransportError("boom")
        if path == "/rate_limit":
            if self.preflight_error is not None:
                raise self.preflight_error
            return ga.Response(200, {}, {"resources": {"core": {"remaining": 4000}}})
        if path == "/search/repositories":
            items = [self.meta(f, r) for f, r in self.repos.items()]
            return ga.Response(200, {}, {"total_count": len(items), "items": items})
        for full, r in self.repos.items():
            base = f"/repos/{full}"
            if path == base:
                return ga.Response(200, {}, self.meta(full, r))
            if path == base + "/stargazers/history":
                if self.history_status != 200:
                    return ga.Response(self.history_status, {}, None)
                body = weeks_for(r["daily"]) if params.get("page", 1) == 1 else []
                return ga.Response(200, {}, body)
            files = r.get("readmes")            # 语言测试用：{文件名: 文本}；缺省时只有 README.md 且不存在
            if path == base + "/readme":
                if files and "README.md" in files:
                    return ga.Response(200, {}, {"content": base64.b64encode(files["README.md"].encode()).decode()})
                return ga.Response(404, {}, None)
            if path == base + "/git/trees/main":
                names = list(files) if files else ["README.md"]
                return ga.Response(200, {}, {"truncated": False,
                                             "tree": [{"path": n, "type": "blob"} for n in names]})
            if path.startswith(base + "/contents/"):
                name = path[len(base + "/contents/"):]
                if files and name in files:
                    return ga.Response(200, {}, {"content": base64.b64encode(files[name].encode()).decode()})
                return ga.Response(404, {}, None)
            if path == base + "/releases":
                return ga.Response(200, {}, r.get("releases", []))     # M5 用例 6：可注入 release 列表
            if path == base + "/languages":
                return ga.Response(200, {}, {"Python": 100})
        return ga.Response(404, {}, None)


def standard_repos():
    # 窗口 10-03..10-10 的新增：a=55，b=25，c=22，d=21（min_gain_window=20）
    return {
        "own/a": {"id": 101, "stars": 500, "daily": {D(2026, 10, 4): 10, D(2026, 10, 5): 10,
                                                   D(2026, 10, 6): 5, D(2026, 10, 7): 5,
                                                   D(2026, 10, 8): 25}},
        "own/b": {"id": 102, "stars": 300, "daily": {D(2026, 10, 8): 25}},
        "own/c": {"id": 103, "stars": 200, "daily": {D(2026, 10, 8): 22}},
        "own/d": {"id": 104, "stars": 100, "daily": {D(2026, 10, 8): 21}},
    }


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class Env(unittest.TestCase):
    """每个测试一套独立临时目录。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="collect_test_")
        self.paths = {
            "state_db": os.path.join(self.tmp, "state.db"),
            "out_dir": os.path.join(self.tmp, "采集包"),
            "log_dir": os.path.join(self.tmp, "采集日志"),
            "bank_dir": os.path.join(self.tmp, "bank"),
            "lock": os.path.join(self.tmp, "collect.lock"),
            "directions": os.path.join(self.tmp, "directions.json"),
            "concepts": os.path.join(self.tmp, "知识地图.json"),
            "config": os.path.join(COLLECTOR, "config.json"),
        }
        os.makedirs(self.paths["bank_dir"])
        with open(self.paths["directions"], "w", encoding="utf-8") as f:
            json.dump({"x": {"domain": "RAG", "topics": ["rag"], "prerequisites": [], "keywords": {}}}, f)
        with open(self.paths["concepts"], "w", encoding="utf-8") as f:     # 测试用知识地图，不读取真实文件
            json.dump({"concepts": CONCEPTS}, f, ensure_ascii=False)
        with open(os.path.join(COLLECTOR, "config.json"), encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.cfg["per_direction_cap"] = 10     # 本类测试关注 M3/M4 行为；方向上限由 CapTest 单独验证（默认配置为 3）
        self.fake = FakeGitHub(standard_repos())
        self.transport = ga.FixtureTransport(handler=self.fake)
        self.clock = Clock(NOW)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def opts(self, **kw):
        base = dict(paths=self.paths, token=TOKEN, transport=self.transport, clock=self.clock,
                    sleep=lambda s: None, config=self.cfg)
        base.update(kw)
        return col.Options(**base)

    def run_once(self, **kw):
        return col.run(self.opts(**kw))

    def packs(self):
        return sorted(glob.glob(os.path.join(self.paths["out_dir"], "采集包_*.json")))

    def pack(self):
        with open(self.packs()[-1], encoding="utf-8") as f:
            return json.load(f)

    def db(self):
        return sqlite3.connect(self.paths["state_db"])

    def watermark(self):
        if not os.path.exists(self.paths["state_db"]):
            return None
        c = self.db()
        row = c.execute("SELECT value FROM meta WHERE key='last_success_until'").fetchone()
        c.close()
        return row[0] if row else None

    def runs(self):
        c = self.db()
        rows = c.execute("SELECT status, pack_file, note FROM runs ORDER BY started_at").fetchall()
        c.close()
        return rows


class FirstRunTest(Env):
    """用例 1：首次运行；另含字段齐全检查（方案 2.6 节）。"""

    def test_first_run_builds_pack_and_watermark(self):
        self.assertEqual(self.run_once(), 0)
        self.assertTrue(os.path.exists(self.paths["state_db"]))
        self.assertEqual(self.watermark(), "2026-10-10T03:00:00Z")   # 窗口终点
        self.assertEqual(len(self.packs()), 1)
        pk = self.pack()
        self.assertEqual(pk["format"], "github-learning-pack/v1")
        # 首次运行窗口 = 终点往前 7 天；star_days 不含终点当天 → 7 个日期（10-03..10-09）
        self.assertEqual(len(pk["run"]["star_days"]), 7)
        self.assertEqual(pk["run"]["star_days"][0], "2026-10-03")
        self.assertEqual(pk["run"]["star_days"][-1], "2026-10-09")
        self.assertIn("首次运行", pk["run"]["gap_note"])
        self.assertIn("热度分未启用", pk["run"]["gap_note"])
        # 按「窗口新增 ÷ 天数」降序：a=55，b=25，c=22，d=21
        names = [p["full_name"] for p in pk["projects"]]
        self.assertEqual(names, ["own/a", "own/b", "own/c", "own/d"])
        for p in pk["projects"]:
            self.assertEqual(set(p.keys()), PROJECT_KEYS)
            self.assertIsNone(p["heat_score"])
            self.assertEqual(p["direction"], "x")                 # topics=[rag] 命中方向 x（M5.1）
            self.assertEqual(p["direction_confidence"], "high")
            self.assertEqual(p["learning_mode"], "delta")         # 方向 x 的前置概念为空
            self.assertTrue(p["untrusted_content"])
            self.assertEqual(p["stars_gained_window"], sum(p["stars_daily"]))
            self.assertEqual(len(p["stars_daily"]), 7)
        self.assertEqual(pk["projects"][0]["stars_gained_window"], 55)     # 10-08 之前的新增都在窗口内
        self.assertEqual(pk["learner_context"]["catalog_file"], "题库目录.md")
        self.assertIn("已出题", pk["learner_context"]["note"])
        # 预览文件
        self.assertEqual(len(glob.glob(os.path.join(self.paths["out_dir"], "*_预览.md"))), 1)
        # 入包仓库状态
        c = self.db()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM repos WHERE status='packed'").fetchone()[0], 4)
        c.close()
        self.assertEqual(self.runs()[0][0], "success")


class SkipAndNetworkTest(Env):
    """用例 2（防重复零网络）与用例 3（预检超时）。"""

    def test_second_run_within_20h_makes_no_requests(self):
        self.assertEqual(self.run_once(), 0)
        before = len(self.transport.calls)
        self.clock.t = NOW + dt.timedelta(hours=10)
        self.assertEqual(self.run_once(), 0)
        self.assertEqual(len(self.transport.calls), before)          # 没有任何网络请求
        self.assertEqual(self.runs()[-1][0], "skipped_recent")

    def test_preflight_timeout_skips_without_moving_watermark(self):
        self.fake.preflight_error = ga.TransportError("timeout")
        self.assertEqual(self.run_once(), 0)
        self.assertEqual(self.runs()[-1][0], "skipped_no_network")
        self.assertIsNone(self.watermark())
        self.assertEqual(self.packs(), [])


class WindowTest(Env):
    """用例 4：断网 3 天后运行，窗口覆盖 3 天，star_days 含 3 个日期（不含终点当天），stars_daily 长度为 3。"""

    def test_three_days_offline(self):
        store = stmod.Store(self.paths["state_db"])
        store.meta_set("last_success_until", "2026-10-07T01:00:00Z")
        store.close()
        self.assertEqual(self.run_once(), 0)
        pk = self.pack()
        self.assertEqual(pk["run"]["star_days"], ["2026-10-07", "2026-10-08", "2026-10-09"])
        for p in pk["projects"]:
            self.assertEqual(len(p["stars_daily"]), 3)
        self.assertIn("上次成功采集为 2026-10-07", pk["run"]["gap_note"])
        self.assertIn("本包覆盖之后 3 天", pk["run"]["gap_note"])
        self.assertEqual(self.watermark(), "2026-10-10T03:00:00Z")


class DeepFailureTest(Env):
    """用例 5：深采中途连续 3 次请求失败 → 退出码 3、partial、不出包、水位线不变；重跑时缓存项目不再请求。"""

    def test_consecutive_failures_then_resume_from_cache(self):
        self.fake.fail_paths = {"/repos/own/b", "/repos/own/c", "/repos/own/d"}
        self.assertEqual(self.run_once(), 3)
        self.assertEqual(self.runs()[-1][0], "partial")
        self.assertEqual(self.packs(), [])
        self.assertIsNone(self.watermark())
        # 第一个项目（own/a）已深采并写入缓存（深采结果含 meta；初筛的 README 缓存不计入）
        c = self.db()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM enrich_cache WHERE payload LIKE '%\"meta\"%'").fetchone()[0], 1)
        c.close()

        # 修复网络后重跑（同一窗口）：own/a 命中深采缓存；所有候选的 README 都命中缓存，不再请求
        self.fake.fail_paths = set()
        self.fake.calls.clear()
        self.assertEqual(self.run_once(force=True), 0)
        self.assertNotIn("/repos/own/a", self.fake.calls)
        self.assertIn("/repos/own/b", self.fake.calls)
        self.assertFalse(any(p.endswith("/readme") for p in self.fake.calls))
        self.assertEqual(len(self.packs()), 1)
        self.assertEqual(self.watermark(), "2026-10-10T03:00:00Z")


class QuestionedTest(Env):
    """题库中的已出题仓库：标为 questioned，且 M3 阶段一律不入包（v1.1 Q3）。"""

    def test_bank_marks_questioned_and_excludes_it(self):
        bank = {"domain": "RAG", "category": "检索", "items": [
            {"id": "RAG-F001", "level": "F", "concepts": ["rag.embedding"], "added": "2026-09-01"},
            {"concepts": ["rag.chunking"], "source_repos": ["own/c"], "added": "2026-09-02"},  # 旧结构无 level
        ]}
        with open(os.path.join(self.paths["bank_dir"], "03_rag.json"), "w", encoding="utf-8") as f:
            json.dump(bank, f, ensure_ascii=False)
        self.assertEqual(self.run_once(), 0)
        pk = self.pack()
        self.assertNotIn("own/c", [p["full_name"] for p in pk["projects"]])
        self.assertIn("rag.embedding", pk["learner_context"]["covered_concepts"])
        # 两道题都计为 F：第二道是旧结构（没有 level），按方案按基础题处理
        self.assertEqual(pk["learner_context"]["domain_counts"]["RAG"], {"F": 2, "X": 0})
        c = self.db()
        row = c.execute("SELECT status, questioned_at FROM repos WHERE full_name='own/c'").fetchone()
        c.close()
        self.assertEqual(row[0], "questioned")
        self.assertEqual(row[1], "2026-09-02")


class EmptyWindowTest(Env):
    """协助决策 9.9 第 2 条：窗口不足一天 → 不出包，runs 记 skipped_recent 并注明「窗口不足一天」，水位线不动。"""

    def test_same_day_window_makes_no_pack_and_keeps_watermark(self):
        store = stmod.Store(self.paths["state_db"])
        store.meta_set("last_success_until", "2026-10-10T03:00:00Z")   # 与本次终点 03:00 同一天、同一时刻
        store.close()
        self.assertEqual(self.run_once(force=True), 0)
        self.assertEqual(self.packs(), [])                              # 不出包
        last = self.runs()[-1]
        self.assertEqual(last[0], "skipped_recent")
        self.assertEqual(last[2], "窗口不足一天")
        self.assertFalse(any("/stargazers/history" in c for c in self.fake.calls))   # 不做 Star 初筛
        self.assertFalse(any("/readme" in c for c in self.fake.calls))              # 也不取 README
        self.assertEqual(self.watermark(), "2026-10-10T03:00:00Z")      # 水位线不动


class QuestionedFromRepoTableTest(Env):
    """第 9.7 节 (c)：题库仓库若已在本地 repos 表中，直接标记，不调用 API；查不到才调用 API。"""

    def test_known_repo_marked_without_api_call_unknown_repo_resolved_by_api(self):
        self.assertEqual(self.run_once(), 0)                      # own/c 入包，写入 repos 表
        bank = {"domain": "RAG", "items": [
            {"concepts": ["rag.chunking"], "source_repos": ["OWN/C", "own/ghost"], "added": "2026-09-02"}]}
        with open(os.path.join(self.paths["bank_dir"], "03_rag.json"), "w", encoding="utf-8") as f:
            json.dump(bank, f, ensure_ascii=False)
        self.fake.calls.clear()
        self.clock.t = NOW + dt.timedelta(days=1)                 # 让窗口非空，确保发现流程真正运行
        self.assertEqual(self.run_once(force=True), 0)
        self.assertNotIn("/repos/OWN/C", self.fake.calls)         # 本地命中：不查 API
        self.assertNotIn("/repos/own/c", self.fake.calls)
        self.assertIn("/repos/own/ghost", self.fake.calls)        # 本地未命中：只这一次调用 API
        c = self.db()
        row = c.execute("SELECT status, questioned_at FROM repos WHERE full_name='own/c'").fetchone()
        c.close()
        self.assertEqual(row[0], "questioned")
        self.assertEqual(row[1], "2026-09-02")
        self.assertNotIn("own/c", [p["full_name"] for p in self.pack()["projects"]])


class WatermarkTest(Env):
    """第 9.7 节 (a)：水位线只前进不回退。"""

    def test_since_run_does_not_move_watermark_backwards(self):
        store = stmod.Store(self.paths["state_db"])
        store.meta_set("last_success_until", "2026-10-10T05:00:00Z")   # 晚于本次窗口终点 03:00
        store.close()
        self.assertEqual(self.run_once(since=D(2026, 10, 9), force=True), 0)
        self.assertEqual(len(self.packs()), 1)                         # 出包成功
        self.assertEqual(self.watermark(), "2026-10-10T05:00:00Z")     # 没有回退到 03:00


class SnapshotTest(Env):
    """第 9.7 节 (b)：Star 快照写入 snapshots 表（只追加），并作为接口不可用时的退化依据。"""

    def snapshot_rows(self, repo_id):
        c = self.db()
        n = c.execute("SELECT COUNT(*) FROM snapshots WHERE repo_id = ?", (repo_id,)).fetchone()[0]
        c.close()
        return n

    def test_snapshots_appended_each_run_and_meta_key_unused(self):
        self.cfg["packed_cooldown_days"] = 0       # 否则第二次运行时仓库处于冷却期，不会进入初筛
        self.assertEqual(self.run_once(), 0)
        self.assertEqual(self.snapshot_rows(101), 1)
        self.clock.t = NOW + dt.timedelta(days=1)
        self.assertEqual(self.run_once(), 0)
        self.assertEqual(self.snapshot_rows(101), 2)                   # 追加，不覆盖
        c = self.db()
        keys = c.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'star_snapshot:%'").fetchone()[0]
        c.close()
        self.assertEqual(keys, 0)

    def test_history_unavailable_falls_back_to_latest_snapshot(self):
        self.cfg["packed_cooldown_days"] = 0       # 让第一次入包的 own/a 在第二次可以再次参与
        self.assertEqual(self.run_once(), 0)       # 第一次：历史接口正常，own/a 快照 = 500
        self.fake.history_status = 404             # 第二次：历史接口不可用，走快照差值
        self.fake.repos["own/a"]["stars"] = 540    # 当前 540 → 估算新增 40
        self.clock.t = NOW + dt.timedelta(days=1)
        self.assertEqual(self.run_once(), 0)
        pk = self.pack()
        self.assertEqual([p["full_name"] for p in pk["projects"]], ["own/a"])
        self.assertEqual(pk["projects"][0]["stars_gained_window"], 40)
        self.assertIn("估算", pk["run"]["gap_note"])
        self.assertEqual(self.snapshot_rows(101), 2)


ZH_README = ("检索增强生成（RAG）是一种把外部知识库与大语言模型结合的方法。本项目提供中文文档、示例和评测脚本，"
             "适合初学者快速搭建知识库问答系统，并支持向量检索与重排序。")
JA_README = ("この リポジトリは検索拡張生成のためのツールです。ナレッジベースと連携して質問に答えます。"
             "ドキュメントは日本語で書かれており、初心者にもわかりやすい構成になっています。")
EN_README = ("This repository provides a complete English guide to retrieval augmented generation, with examples, "
             "benchmarks and step by step tutorials for building knowledge base assistants.")


class LanguageTest(Env):
    """M4 验收用例 2、3：文档语言来自 README（不是编程语言 language）；英文版 README 进入 doc_langs_available。"""

    def setUp(self):
        super().setUp()
        repos = {
            "own/zh": {"id": 201, "stars": 400, "daily": {D(2026, 10, 8): 30}, "desc": "一个中文 RAG 项目",
                       "readmes": {"README.md": ZH_README}},
            "own/ja": {"id": 202, "stars": 300, "daily": {D(2026, 10, 8): 30}, "desc": "RAG tool",
                       "readmes": {"README.md": JA_README, "README.en.md": EN_README}},
            "own/cn": {"id": 203, "stars": 250, "daily": {D(2026, 10, 8): 30},
                       "desc": "A retrieval augmented generation toolkit for developers",
                       "readmes": {"README.md": ZH_README}},
        }
        self.fake = FakeGitHub(repos)
        self.transport = ga.FixtureTransport(handler=self.fake)

    def test_language_from_readme_and_english_variant(self):
        self.assertEqual(self.run_once(), 0)
        by = {p["full_name"]: p for p in self.pack()["projects"]}
        self.assertEqual(by["own/zh"]["language"], "Python")          # 编程语言不参与文档语言判断
        self.assertEqual(by["own/zh"]["doc_lang"], "zh")
        self.assertEqual(by["own/zh"]["lang_group"], "zh")
        self.assertEqual(by["own/ja"]["doc_lang"], "ja")
        self.assertEqual(by["own/ja"]["lang_group"], "ja")
        self.assertIn("ja", by["own/ja"]["doc_langs_available"])
        self.assertIn("en", by["own/ja"]["doc_langs_available"])
        self.assertTrue(by["own/ja"]["readme_en_sections"])
        self.assertTrue(all(p["heat_score"] is None for p in by.values()))   # 冷启动（样本 3 < 30）

    def test_english_description_chinese_readme_is_zh_and_readme_fetched_once(self):
        # M4 验收用例 2b（协助决策 9.9 第 3 条）：描述英文、README 中文 → 语言组 zh；
        # README 在初筛取得并写入 enrich_cache，深采复用，全程只请求一次
        self.assertEqual(self.run_once(), 0)
        by = {p["full_name"]: p for p in self.pack()["projects"]}
        self.assertEqual(by["own/cn"]["doc_lang"], "zh")
        self.assertEqual(by["own/cn"]["lang_group"], "zh")
        self.assertEqual(self.fake.calls.count("/repos/own/cn/readme"), 1)


class ReadmeGateTest(Env):
    """协助决策 9.9 第 3 条：只对通过 min_gain_window 的候选取 README；其余只用描述识别语言组。"""

    def setUp(self):
        super().setUp()
        repos = standard_repos()
        repos["own/low"] = {"id": 105, "stars": 50, "daily": {D(2026, 10, 8): 5},   # 窗口新增 5 < 20
                            "desc": "低增长项目", "readmes": {"README.md": ZH_README}}
        self.fake = FakeGitHub(repos)
        self.transport = ga.FixtureTransport(handler=self.fake)

    def test_readme_only_for_candidates_over_min_gain(self):
        self.assertEqual(self.run_once(), 0)
        self.assertFalse(any(p == "/repos/own/low/readme" for p in self.fake.calls))
        for full in ("own/a", "own/b", "own/c", "own/d"):
            self.assertEqual(self.fake.calls.count(f"/repos/{full}/readme"), 1, full)
        self.assertNotIn("own/low", [p["full_name"] for p in self.pack()["projects"]])


class KeywordRotationTest(Env):
    """M4 验收用例 6（运行级）：关键词断点只在出包成功后保存；失败的运行不跳过任何查询。"""

    def write_directions(self):
        kws = {"zh": [f"词{i}" for i in range(20)]}       # 队列 20 个，每次 12 个
        with open(self.paths["directions"], "w", encoding="utf-8") as f:
            json.dump({"x": {"domain": "RAG", "topics": ["rag"], "prerequisites": [], "keywords": kws}},
                      f, ensure_ascii=False)

    def rotation(self):
        c = self.db()
        row = c.execute("SELECT value FROM meta WHERE key='kw_rotation_zh'").fetchone()
        c.close()
        return json.loads(row[0])["pos"] if row else None

    def test_rotation_saved_on_success_only(self):
        self.write_directions()
        self.assertEqual(self.run_once(), 0)
        self.assertEqual(self.rotation(), 12)                  # 第 1–12 个
        self.clock.t = NOW + dt.timedelta(days=1)
        self.assertEqual(self.run_once(), 0)
        self.assertEqual(self.rotation(), 4)                   # 第 13–20 个 + 回绕第 1–4 个
        self.clock.t = NOW + dt.timedelta(days=2)
        self.fake.fail_paths = {"/search/repositories"}        # 搜索网络失败：退出码 3
        self.assertEqual(self.run_once(), 3)
        self.assertEqual(self.rotation(), 4)                   # 断点不前进，下次仍从这里开始


class SearchNetworkFailureTest(Env):
    """协助决策 9.10 第 4 条：搜索阶段网络错误（重试耗尽）→ 退出码 3、记 partial、水位线不变、不出包。"""

    def test_search_network_failure_is_partial_and_keeps_watermark(self):
        self.assertEqual(self.run_once(), 0)                   # 先成功一次，水位线前进
        wm = self.watermark()
        packs = self.packs()
        self.clock.t = NOW + dt.timedelta(days=1)
        self.fake.fail_paths = {"/search/repositories"}
        self.assertEqual(self.run_once(force=True), 3)
        self.assertEqual(self.runs()[-1][0], "partial")
        self.assertEqual(self.watermark(), wm)                  # 水位线不动
        self.assertEqual(self.packs(), packs)                   # 没有新包


class ProgramErrorTest(Env):
    """协助决策 9.10 第 4 条：程序自身异常 → 退出码 1、记 failed，水位线不动。"""

    def test_program_bug_is_failed_not_partial(self):
        def boom(path, params):
            if path == "/search/repositories":
                raise RuntimeError("内部错误（测试）")
            return self.fake(path, params)
        self.transport = ga.FixtureTransport(handler=boom)
        self.assertEqual(self.run_once(), 1)
        self.assertEqual(self.runs()[-1][0], "failed")
        self.assertIsNone(self.watermark())


class LockTest(Env):
    """用例 12：两个实例同时运行，第二个退出码 4；残留锁（超过 2 小时）会被覆盖。"""

    def test_fresh_lock_blocks_second_instance(self):
        with open(self.paths["lock"], "w", encoding="utf-8") as f:
            f.write("pid=1\n")
        self.assertEqual(self.run_once(), 4)
        self.assertTrue(os.path.exists(self.paths["lock"]))     # 不删除别人的锁
        self.assertEqual(self.packs(), [])

    def test_stale_lock_is_overwritten_and_released(self):
        with open(self.paths["lock"], "w", encoding="utf-8") as f:
            f.write("pid=1\n")
        old = time.time() - 3 * 3600
        os.utime(self.paths["lock"], (old, old))
        self.assertEqual(self.run_once(), 0)
        self.assertFalse(os.path.exists(self.paths["lock"]))    # 正常结束后删除


class SecretTest(Env):
    """用例 13：日志与采集包中找不到 Token 字符串。"""

    def test_token_not_in_logs_or_pack(self):
        # 让预检异常信息里带上 Token，验证脱敏（文件与控制台输出都不能出现）
        self.fake.preflight_error = ga.TransportError(f"timeout with {TOKEN}")
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.run_once()
        self.assertNotIn(TOKEN, buf.getvalue())
        self.fake.preflight_error = None
        self.run_once(force=True)                              # 再跑一次成功运行
        found = []
        for p in glob.glob(os.path.join(self.paths["log_dir"], "*.log")) + \
                glob.glob(os.path.join(self.paths["out_dir"], "*")):
            with open(p, encoding="utf-8") as f:
                if TOKEN in f.read():
                    found.append(p)
        self.assertEqual(found, [])
        with open(glob.glob(os.path.join(self.paths["log_dir"], "*.log"))[0], encoding="utf-8") as f:
            self.assertIn("***", f.read())


class DryRunTest(Env):
    """用例 14：--dry-run 不写采集包，repos 与水位线不变。"""

    def test_dry_run_changes_nothing(self):
        self.assertEqual(self.run_once(), 0)                    # 先有一次真实运行
        packs_before = self.packs()
        c = self.db()
        repos_before = c.execute("SELECT repo_id, status, packed_in FROM repos ORDER BY repo_id").fetchall()
        c.close()
        wm_before = self.watermark()
        self.clock.t = NOW + dt.timedelta(days=1)
        self.assertEqual(self.run_once(dry_run=True, force=True), 0)
        self.assertEqual(self.packs(), packs_before)
        c = self.db()
        repos_after = c.execute("SELECT repo_id, status, packed_in FROM repos ORDER BY repo_id").fetchall()
        c.close()
        self.assertEqual(repos_after, repos_before)
        self.assertEqual(self.watermark(), wm_before)

    def test_dry_run_without_database_creates_none(self):
        self.assertEqual(self.run_once(dry_run=True), 0)
        self.assertFalse(os.path.exists(self.paths["state_db"]))
        self.assertEqual(self.packs(), [])


class ConfigTest(Env):
    def test_missing_token_is_config_error_without_requests(self):
        self.assertEqual(self.run_once(token=None), 2)
        self.assertEqual(self.transport.calls, [])


RELEASE_V1 = [{"tag_name": "v1.0.0", "name": "v1.0.0", "body": "first release", "draft": False,
               "published_at": "2026-08-01T00:00:00Z"}]
RELEASE_V2 = [{"tag_name": "v2.0.0", "name": "v2.0.0", "body": "major rewrite", "draft": False,
               "published_at": "2026-10-10T00:00:00Z"}] + RELEASE_V1


class M5Base(Env):
    def write_bank(self, items: list, domain: str = "RAG") -> None:
        with open(os.path.join(self.paths["bank_dir"], "03_rag.json"), "w", encoding="utf-8") as f:
            json.dump({"domain": domain, "items": items}, f, ensure_ascii=False)

    def write_directions(self, prereqs: list) -> None:
        with open(self.paths["directions"], "w", encoding="utf-8") as f:
            json.dump({"x": {"domain": "RAG", "topics": ["rag"], "prerequisites": prereqs, "keywords": {}}}, f)

    def read_logs(self) -> str:
        text = ""
        for p in glob.glob(os.path.join(self.paths["log_dir"], "*.log")):
            with open(p, encoding="utf-8") as f:
                text += f.read()
        return text

    def preview(self) -> str:
        with open(glob.glob(os.path.join(self.paths["out_dir"], "*_预览.md"))[0], encoding="utf-8") as f:
            return f.read()

    def packed_names(self) -> list:
        return [p["full_name"] for p in self.pack()["projects"]]

    def project(self, full: str) -> dict:
        return next(p for p in self.pack()["projects"] if p["full_name"] == full)


class CapTest(M5Base):
    """M5.2 同方向上限：standard_repos 的 4 个候选都属方向 x，上限 3 → 入包 3 个，超出部分记日志。"""

    def setUp(self):
        super().setUp()
        self.cfg["per_direction_cap"] = 3      # 与 config.json 默认值一致

    def test_same_direction_capped_and_logged(self):
        self.assertEqual(self.run_once(), 0)
        self.assertEqual(self.packed_names(), ["own/a", "own/b", "own/c"])     # own/d（最低分）超出上限
        self.assertIn("同方向上限 3：跳过 1 个超出上限的候选", self.read_logs())


class ReviseTest(M5Base):
    """M5 验收用例 6、7：已出题仓库的复收条件（方案 M5.4）。"""

    def test_release_bump_after_35_days_triggers_update(self):                 # 用例 6
        self.fake.repos["own/a"]["releases"] = RELEASE_V1
        self.write_bank([{"id": "RAG-F001", "level": "F", "concepts": ["rag.chunking"],
                          "source_repos": ["own/a"], "added": "2026-09-05"}])   # 距今 35 天
        self.assertEqual(self.run_once(), 0)
        self.assertNotIn("own/a", self.packed_names())                          # 基线 v1.0.0：无新版本，不复收
        c = self.db()
        tag = c.execute("SELECT last_release_tag FROM repos WHERE full_name='own/a'").fetchone()[0]
        c.close()
        self.assertEqual(tag, "v1.0.0")

        self.fake.repos["own/a"]["releases"] = RELEASE_V2                       # 发布 v2.0.0
        self.fake.repos["own/a"]["daily"][D(2026, 10, 10)] = 25                 # 本次窗口新增 25（≥ 20）
        self.clock.t = NOW + dt.timedelta(days=1)
        self.assertEqual(self.run_once(force=True), 0)
        pa = self.project("own/a")
        self.assertEqual(pa["learning_mode"], "update")
        self.assertIn("v2", pa["mode_reason"])
        self.assertEqual(pa["diff_evidence"]["release_change"], {"from": "v1.0.0", "to": "v2.0.0"})

    def test_questioned_10_days_ago_not_repacked(self):                        # 用例 7
        self.fake.repos["own/a"]["releases"] = RELEASE_V2
        self.write_bank([{"id": "RAG-F001", "level": "F", "concepts": ["rag.chunking"],
                          "source_repos": ["own/a"], "added": "2026-09-30"}])   # 距今 10 天
        self.assertEqual(self.run_once(), 0)
        self.assertNotIn("own/a", self.packed_names())
        self.assertFalse(any(c.endswith("/own/a/readme") or c.endswith("/own/a/stargazers/history")
                             for c in self.fake.calls))                         # 不做初筛，也不取 README


class LearningModeTest(M5Base):
    """M5 验收用例 4、5（运行级）：前置概念齐全 → delta；缺两个 → foundation 并列出这两个概念。"""

    def test_two_missing_prerequisites_gives_foundation(self):                # 用例 5
        self.write_directions(["rag.vector_db", "rag.chunking"])
        self.assertEqual(self.run_once(), 0)
        for p in self.pack()["projects"]:
            self.assertEqual(p["learning_mode"], "foundation")
            self.assertEqual(p["prerequisites_missing"],
                             [{"key": "rag.vector_db", "name": "向量数据库"},
                              {"key": "rag.chunking", "name": "文本切块"}])

    def test_all_prerequisites_covered_gives_delta(self):                     # 用例 4
        self.write_directions(["rag.vector_db", "rag.chunking"])
        self.write_bank([{"id": "RAG-F001", "level": "F", "concepts": ["rag.vector_db", "rag.chunking"],
                          "added": "2026-09-01"}])
        self.assertEqual(self.run_once(), 0)
        for p in self.pack()["projects"]:
            self.assertEqual(p["learning_mode"], "delta")
            self.assertEqual(p["prerequisites_missing"], [])


class DiffEvidenceTest(M5Base):
    """M5.5（运行级）：同方向已出题仓库 own/b 没有深采缓存 → 对比项目列出题号，并注明「对比项目无缓存数据」。"""

    def test_compared_repo_without_cache_is_noted(self):
        self.write_bank([{"id": "RAG-F001", "level": "F", "concepts": ["rag.chunking"],
                          "source_repos": ["own/b"], "added": "2026-09-02"}])
        self.assertEqual(self.run_once(), 0)
        self.assertNotIn("own/b", self.packed_names())                          # 无复收条件，不入包
        de = self.project("own/a")["diff_evidence"]
        self.assertEqual(de["compared_with"], [{"full_name": "own/b", "question_ids": ["RAG-F001"]}])
        self.assertEqual(de["new_dependencies"], [])
        self.assertEqual(de["note"], "对比项目无缓存数据")


class WordingTest(M5Base):
    """M5 验收用例 10：输出中不出现「已掌握」「已学会」等表述（学习结果不由采集器判断）。"""

    def test_no_mastery_claims_in_pack_or_preview(self):
        self.write_bank([{"id": "RAG-F001", "level": "F", "concepts": ["rag.chunking"],
                          "source_repos": ["own/b"], "added": "2026-09-02"}])
        self.assertEqual(self.run_once(), 0)
        text = json.dumps(self.pack(), ensure_ascii=False) + self.preview()
        for word in ("已掌握", "已学会"):
            self.assertNotIn(word, text)
        self.assertIn("不代表学习结果", self.pack()["learner_context"]["note"])


RELEASE_V11 = [{"tag_name": "v1.1.0", "name": "v1.1.0", "body": "minor", "draft": False,
                "published_at": "2026-10-10T00:00:00Z"}] + RELEASE_V1


class GainBaselineTest(M5Base):
    """验收用例 A（协助决策 9.10 第 2 条）：题库仓库第一次被观察到时补日均基线，这一次不据此复收；
    之后日均新增 ≥ 2 倍时复收，release_change 为 null（tag 未变）。"""

    def test_baseline_filled_on_first_observation_then_daily_doubling_triggers_update(self):
        self.write_bank([{"id": "RAG-F001", "level": "F", "concepts": ["rag.chunking"],
                          "source_repos": ["own/a"], "added": "2026-09-05"}])
        self.assertEqual(self.run_once(), 0)
        self.assertNotIn("own/a", self.packed_names())                  # 第一次观察：只补基线，不复收
        c = self.db()
        base = c.execute("SELECT gain_at_first_pack FROM repos WHERE full_name='own/a'").fetchone()[0]
        c.close()
        self.assertAlmostEqual(base, 55 / 7, places=6)                  # 7 天窗口新增 55 → 日均 7.857…

        self.fake.repos["own/a"]["daily"][D(2026, 10, 10)] = 25        # 次日：1 天新增 25，日均 25 ≥ 2 × 7.857
        self.clock.t = NOW + dt.timedelta(days=1)
        self.assertEqual(self.run_once(force=True), 0)
        pa = self.project("own/a")
        self.assertEqual(pa["learning_mode"], "update")
        self.assertIn("增长触发", pa["mode_reason"])
        self.assertIsNone(pa["diff_evidence"]["release_change"])        # tag 未变 → null


class TagChangeTest(M5Base):
    """验收用例 B（协助决策 9.10 第 3 条）：最新 tag 与上次记录不同时填 release_change，即使不是主版本变化；
    mode_reason 写明触发原因是增长。"""

    def test_minor_tag_change_fills_release_change_and_growth_reason(self):
        self.fake.repos["own/a"]["releases"] = RELEASE_V1
        self.write_bank([{"id": "RAG-F001", "level": "F", "concepts": ["rag.chunking"],
                          "source_repos": ["own/a"], "added": "2026-09-05"}])
        self.assertEqual(self.run_once(), 0)                            # 基线：tag v1.0.0
        self.fake.repos["own/a"]["releases"] = RELEASE_V11              # v1.1.0：主版本仍为 1，不构成发布触发
        self.fake.repos["own/a"]["daily"][D(2026, 10, 10)] = 25
        self.clock.t = NOW + dt.timedelta(days=1)
        self.assertEqual(self.run_once(force=True), 0)
        pa = self.project("own/a")
        self.assertEqual(pa["learning_mode"], "update")
        self.assertIn("增长触发", pa["mode_reason"])
        self.assertEqual(pa["diff_evidence"]["release_change"], {"from": "v1.0.0", "to": "v1.1.0"})


class NoComparisonNoteTest(M5Base):
    """验收用例 C（协助决策 9.10 第 5 条）：没有同方向已出题项目时，备注指向题库目录，而不是留空。"""

    def test_empty_comparison_gets_direction_note(self):
        self.assertEqual(self.run_once(), 0)                            # 题库为空，没有已出题仓库
        de = self.project("own/a")["diff_evidence"]
        self.assertEqual(de["compared_with"], [])
        self.assertEqual(de["new_dependencies"], [])
        self.assertEqual(de["note"],
                         "本方向尚无已出题项目可对比，请参考 题库目录.md 中同领域的题目判断差异")


class SkippedProjectTest(M5Base):
    """协助决策 9.10 第 6 条（回归，无单独验收用例）：单个项目深采失败 → 跳过、退出码 0，
    保持 seen；runs.note 记录跳过个数；预览末尾列出被跳过的仓库。"""

    def test_failed_project_stays_seen_and_is_reported(self):
        self.fake.status_override = {"/repos/own/b": 422}
        self.assertEqual(self.run_once(), 0)
        self.assertNotIn("own/b", self.packed_names())
        c = self.db()
        status = c.execute("SELECT status FROM repos WHERE full_name='own/b'").fetchone()[0]
        c.close()
        self.assertEqual(status, "seen")
        self.assertEqual(self.runs()[-1][2], "跳过 1 个项目（保持 seen，下次运行自动重试）")
        preview = self.preview()
        self.assertIn("## 本次被跳过的项目", preview)
        self.assertIn("- own/b：深采失败", preview)


class GainUnitMigrationTest(unittest.TestCase):
    """协助决策 9.10 第 2 条：旧的「窗口总量」基线只迁移一次（清空），之后的日均基线保留。"""

    def test_legacy_totals_cleared_once(self):
        tmp = tempfile.mkdtemp(prefix="collect_mig_")
        try:
            path = os.path.join(tmp, "state.db")
            st = stmod.Store(path)
            st.upsert_repo(1, "own/x", "u", "2026-10-01T00:00:00Z")
            st.conn.execute("UPDATE repos SET gain_at_first_pack = 55 WHERE repo_id = 1")
            st.conn.execute("DELETE FROM meta WHERE key = 'gain_unit'")     # 模拟 M5 之前的旧库
            st.close()
            st = stmod.Store(path)                                          # 迁移：旧总量被清空
            self.assertIsNone(st.get_repo(1)["gain_at_first_pack"])
            st.set_gain_baseline(1, 7.5)
            st.close()
            st = stmod.Store(path)                                          # 再次打开：不再迁移
            self.assertEqual(st.get_repo(1)["gain_at_first_pack"], 7.5)
            st.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
