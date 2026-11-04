"""第 2 步：github_api.py 与 store.py 的单元测试（全部离线）。

覆盖：M3 用例 3（预检失败）、用例 13（Token 不泄露）的 HTTP 层部分，
以及限额、重试、连续失败中断与存储层的基本行为。
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import github_api as ga  # noqa: E402
import store  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
FAKE_TOKEN = "ghp_FAKETOKEN_for_tests_only_0123456789"


def resp(status=200, headers=None, body=None):
    return ga.Response(status, {k.lower(): v for k, v in (headers or {}).items()}, body)


class Recorder:
    """记录 sleep 调用，不真的等待。"""

    def __init__(self):
        self.sleeps = []

    def __call__(self, seconds):
        self.sleeps.append(seconds)


class FixtureNameTest(unittest.TestCase):
    def test_mapping_matches_shipped_fixture(self):
        name = ga.fixture_name("/repos/psf/requests/stargazers/history", {"per_page": 2})
        self.assertEqual(name, "repos_psf_requests_stargazers_history_per_page=2.json")
        self.assertTrue(os.path.isfile(os.path.join(FIXTURES, name)))

    def test_params_sorted_and_sanitized(self):
        name = ga.fixture_name("/search/repositories", {"q": "topic:rag stars:>=30", "page": 1})
        self.assertEqual(name, "search_repositories_page=1_q=topic_rag_stars__=30.json")

    def test_fixture_transport_reads_wrapped_fixture(self):
        t = ga.FixtureTransport(FIXTURES)
        r = t.get("/repos/psf/requests/stargazers/history", {"per_page": 2})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.body[0]["week"], 1791072000)
        self.assertEqual(len(t.calls), 1)

    def test_missing_fixture_raises(self):
        t = ga.FixtureTransport(FIXTURES)
        with self.assertRaises(ga.FixtureMissing):
            t.get("/repos/nobody/none")


class RedactTest(unittest.TestCase):
    def test_token_and_bearer_removed(self):
        s = f"Authorization: Bearer {FAKE_TOKEN} failed; token={FAKE_TOKEN}"
        out = ga.redact(s, FAKE_TOKEN)
        self.assertNotIn(FAKE_TOKEN, out)
        self.assertIn("***", out)


class RetryAndLimitTest(unittest.TestCase):
    def make(self, handler):
        logs = []
        rec = Recorder()
        api = ga.GitHubAPI(ga.FixtureTransport(handler=handler), FAKE_TOKEN,
                           sleep=rec, now=lambda: 1_000.0, mono=lambda: 0.0,
                           log=lambda lv, m: logs.append((lv, m)))
        return api, rec, logs

    def test_5xx_retried_twice_then_request_failed(self):
        api, rec, logs = self.make(lambda p, q: resp(502))
        with self.assertRaises(ga.RequestFailed):
            api.get("/repos/a/b")
        self.assertEqual(api.calls, 3)                 # 1 次 + 2 次重试
        self.assertEqual(rec.sleeps, [2, 5])           # 间隔 2 秒、5 秒

    def test_network_error_retried_then_fails(self):
        def boom(p, q):
            raise ga.TransportError("timeout")
        api, rec, _ = self.make(boom)
        with self.assertRaises(ga.RequestFailed):
            api.get("/repos/a/b")
        self.assertEqual(api.calls, 3)

    def test_three_consecutive_failures_are_fatal(self):
        api, _, _ = self.make(lambda p, q: resp(500))
        for _ in range(2):
            with self.assertRaises(ga.RequestFailed):
                api.get("/x")
        with self.assertRaises(ga.FatalNetwork):
            api.get("/x")

    def test_success_resets_consecutive_failures(self):
        state = {"n": 0}

        def handler(p, q):
            state["n"] += 1
            return resp(500) if state["n"] <= 3 else resp(200, body={"ok": True})

        api, _, _ = self.make(handler)
        with self.assertRaises(ga.RequestFailed):
            api.get("/x")                      # 第一个请求：3 次都是 500 → 失败，连续失败计 1
        r = api.get("/x")                      # 第二个请求：返回 200 → 成功，计数清零
        self.assertEqual(r.status, 200)
        self.assertEqual(api.consecutive_failures, 0)

    def test_retry_after_is_honoured(self):
        seq = [resp(403, {"retry-after": "7"}), resp(200, body=[])]
        api, rec, _ = self.make(lambda p, q: seq.pop(0))
        self.assertEqual(api.get("/x").status, 200)
        self.assertEqual(rec.sleeps, [7.0])

    def test_rate_reset_beyond_ten_minutes_exhausts_budget(self):
        headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(1_000 + 3_600)}
        api, _, _ = self.make(lambda p, q: resp(403, headers))
        with self.assertRaises(ga.BudgetExhausted):
            api.get("/x")

    def test_preflight_timeout_is_not_retried(self):
        def boom(p, q):
            raise ga.TransportError("timeout")
        api, rec, _ = self.make(boom)
        with self.assertRaises(ga.TransportError):
            api.preflight(timeout=5)
        self.assertEqual(api.calls, 1)
        self.assertEqual(rec.sleeps, [])

    def test_search_interval_enforced(self):
        clock = {"t": 0.0}
        rec = Recorder()
        api = ga.GitHubAPI(ga.FixtureTransport(handler=lambda p, q: resp(200, body={"items": []})),
                           FAKE_TOKEN, sleep=rec, now=lambda: 0.0, mono=lambda: clock["t"])
        api.search_repos("topic:rag")
        clock["t"] = 0.5
        api.search_repos("topic:rag")
        self.assertEqual(len(rec.sleeps), 1)
        self.assertAlmostEqual(rec.sleeps[0], 1.6, places=3)

    def test_token_never_reaches_log(self):
        api, _, logs = self.make(lambda p, q: resp(500))
        with self.assertRaises(ga.RequestFailed):
            api.get("/x")
        for lv, msg in logs:
            self.assertNotIn(FAKE_TOKEN, msg)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "state.db")

    def test_schema_created_and_idempotent(self):
        s = store.Store(self.db)
        s.close()
        s2 = store.Store(self.db)           # 再次打开不报错
        tables = {r[0] for r in s2.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        s2.close()
        self.assertTrue({"meta", "runs", "repos", "candidate_gains", "enrich_cache", "snapshots"} <= tables)

    def test_snapshots_append_only_and_latest_wins(self):
        s = store.Store(self.db)
        self.assertIsNone(s.latest_snapshot(9))
        s.add_snapshot(9, 40, "2026-10-08T03:00:00Z")
        s.add_snapshot(9, 55, "2026-10-09T03:00:00Z")
        latest = s.latest_snapshot(9)
        self.assertEqual((latest["stars"], latest["taken_at"]), (55, "2026-10-09T03:00:00Z"))
        self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM snapshots WHERE repo_id = 9").fetchone()[0], 2)
        self.assertIsNone(s.latest_snapshot(10))           # 不同仓库互不影响
        s.close()

    def test_meta_and_watermark(self):
        s = store.Store(self.db)
        self.assertIsNone(s.last_success_until())
        s.meta_set("last_success_until", "2026-10-10T03:00:00Z")
        s.meta_set_json("kw_rotation_zh", {"pos": 3})
        self.assertEqual(s.last_success_until(), "2026-10-10T03:00:00Z")
        self.assertEqual(s.meta_get_json("kw_rotation_zh"), {"pos": 3})
        s.close()

    def test_repo_lifecycle(self):
        s = store.Store(self.db)
        s.upsert_repo(42, "owner/name", "https://github.com/owner/name", "2026-10-10T00:00:00Z")
        self.assertEqual(s.get_repo(42)["status"], "seen")
        s.mark_packed(42, "run1", "2026-10-10T03:00:00Z", 55, "v1.0.0")
        r = s.get_repo(42)
        self.assertEqual((r["status"], r["packed_in"], r["gain_at_first_pack"]), ("packed", "run1", 55))
        s.set_repo_status(42, "questioned", None, "2026-10-01")
        self.assertEqual(s.repo_by_full_name("OWNER/name")["questioned_at"], "2026-10-01")
        s.close()

    def test_candidate_gains_write_baseline_delete(self):
        s = store.Store(self.db)
        s.add_candidate_gain("r1", 1, "en", 80, 8, "2026-10-10T03:00:00Z")
        s.add_candidate_gain("r1", 2, "zh", 16, 8, "2026-10-10T03:00:00Z")
        s.add_candidate_gain("old", 3, "en", 5, 8, "2026-07-01T03:00:00Z")      # 超出 60 天，不进基线
        rows = s.baseline_rows("2026-08-11T03:00:00Z")
        self.assertEqual(sorted((r["lang_group"], r["gain"], r["days"]) for r in rows),
                         [("en", 80, 8), ("zh", 16, 8)])
        s.delete_candidate_gains("r1")
        self.assertEqual(len(s.baseline_rows("2026-08-11T03:00:00Z")), 0)
        s.close()

    def test_candidate_gains_migrated_from_m3_schema(self):
        # M3 建的表没有 recorded_at；打开时自动补上，已有数据不丢
        import sqlite3
        c = sqlite3.connect(self.db)
        c.execute("CREATE TABLE candidate_gains (run_id TEXT, repo_id INTEGER, lang_group TEXT, "
                  "gain INTEGER, days INTEGER, PRIMARY KEY (run_id, repo_id))")
        c.execute("INSERT INTO candidate_gains VALUES ('old', 9, 'en', 30, 8)")
        c.commit()
        c.close()
        s = store.Store(self.db)
        cols = {r[1] for r in s.conn.execute("PRAGMA table_info(candidate_gains)")}
        self.assertIn("recorded_at", cols)
        self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM candidate_gains").fetchone()[0], 1)
        s.close()

    def test_cache_roundtrip(self):
        s = store.Store(self.db)
        s.cache_put(7, "run1", "2026-10-10T03:00:00Z", {"readme_sections": [{"heading": "x", "text": "y"}]})
        c = s.cache_get(7)
        self.assertEqual(c["run_id"], "run1")
        self.assertEqual(c["payload"]["readme_sections"][0]["heading"], "x")
        self.assertIsNone(s.cache_get(8))
        s.close()


if __name__ == "__main__":
    unittest.main()
