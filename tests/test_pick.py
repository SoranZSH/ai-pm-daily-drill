# -*- coding: utf-8 -*-
"""M2 验收用例：选题（前置解锁、新题优先）与计数。全部使用临时目录，不碰真实数据。

运行：在 面试英语题库 目录执行  python -m unittest discover -s tests -v
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import daily  # noqa: E402
from ui import state  # noqa: E402

TODAY = dt.date.today()


def d(n):
    return (TODAY - dt.timedelta(days=n)).isoformat()


def q(qid, level="F", prereq=None, added=None, legacy=False):
    it = {"id": qid, "difficulty": "中等", "tags": ["t"], "q_cn": "题目 " + qid, "q_en": "Q?",
          "a_en": "a", "a_cn": "b", "key_phrases": [], "approach": "c", "tips": "d"}
    if not legacy:
        it.update({"level": level, "kind": "knowledge", "concepts": ["x.y"],
                   "prereq": prereq or [], "added": added or d(60)})
    return it


class PickTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bank = os.path.join(self.tmp, "bank")
        os.makedirs(self.bank)
        cfg = os.path.join(self.tmp, "题库路径.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"bank_dir": self.bank, "fresh_days": 21}, f)
        self._saved = (daily.BANK_CONFIG, daily.HISTORY, daily.DATA_DIR)
        daily.BANK_CONFIG = cfg
        daily.DATA_DIR = os.path.join(self.tmp, "data")
        daily.HISTORY = os.path.join(daily.DATA_DIR, "history.json")

    def tearDown(self):
        daily.BANK_CONFIG, daily.HISTORY, daily.DATA_DIR = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_bank(self, items):
        with open(os.path.join(self.bank, "04_agents.json"), "w", encoding="utf-8") as f:
            json.dump({"category": "智能体与工具", "category_en": "Agents", "domain": "AGT",
                       "items": items}, f, ensure_ascii=False)

    def hist(self, studied=(), srs=None):
        h = state.load()
        for qid, day in studied:
            h["study"]["days"].setdefault(day, []).append(qid)
        h["srs"] = srs or {}
        state.save(h)
        return state.load()

    def pick_many(self, h, items, salts=20):
        return {state._pick(items, h, salt=f"|t{i}" if i else "")["id"] for i in range(salts)}

    # 1 未练前置时绝不出拓展题
    def test_01_locked_x_never_picked(self):
        items = [q("AGT-F001"), q("AGT-X001", "X", ["AGT-F001"])]
        self.write_bank(items)
        h = self.hist()
        self.assertEqual(self.pick_many(h, items), {"AGT-F001"})

    # 2 前置练完后拓展题解锁
    def test_02_unlocked_after_prereq(self):
        items = [q("AGT-F001"), q("AGT-X001", "X", ["AGT-F001"])]
        self.write_bank(items)
        h = self.hist(studied=[("AGT-F001", d(1))])
        self.assertEqual(state._pick(items, h)["id"], "AGT-X001")

    # 3 前置已不在题库 → 视为已解锁
    def test_03_missing_prereq_counts_as_done(self):
        items = [q("AGT-X001", "X", ["OLD-F009"])]
        self.write_bank(items)
        self.assertEqual(state._pick(items, self.hist())["id"], "AGT-X001")

    # 4 新鲜题优先
    def test_04_fresh_first(self):
        items = [q("AGT-F001", added=d(60)), q("AGT-F002", added=d(0))]
        self.write_bank(items)
        self.assertEqual(self.pick_many(self.hist(), items), {"AGT-F002"})

    # 5 到期复习题最优先
    def test_05_due_review_first(self):
        items = [q("AGT-F001", added=d(0)), q("AGT-F002")]
        self.write_bank(items)
        h = self.hist(studied=[("AGT-F002", d(3))],
                      srs={"AGT-F002": {"level": 0, "due": d(0), "reps": 1}})
        self.assertEqual(state._pick(items, h)["id"], "AGT-F002")

    # 6 换题：不出当前题、不出被锁的拓展题、不出复习题
    def test_06_swap_rules(self):
        items = [q("AGT-F001"), q("AGT-F002"), q("AGT-F003"), q("AGT-X001", "X", ["AGT-F001"])]
        self.write_bank(items)
        h = self.hist(studied=[("AGT-F003", d(3))],
                      srs={"AGT-F003": {"level": 0, "due": d(0), "reps": 1}})
        h["drawn"][state._key()] = ["AGT-F002"]
        for i in range(20):
            h2 = json.loads(json.dumps(h))
            h2["drawn"][state._key()] = ["AGT-F002"]
            got = state._pick(items, h2, exclude={"AGT-F002"}, salt=f"|swap{i}")["id"]
            self.assertNotIn(got, {"AGT-F002", "AGT-X001", "AGT-F003"})

    # 7 全部被锁（数据异常）时仍能出一道未练过的基础题
    def test_07_all_locked_fallback(self):
        items = [q("AGT-F001", prereq=["AGT-F002"]), q("AGT-F002", prereq=["AGT-F001"])]
        self.write_bank(items)
        self.assertIn(state._pick(items, self.hist())["id"], {"AGT-F001", "AGT-F002"})

    # 8 旧格式题目正常参与
    def test_08_legacy_items(self):
        items = [q("DA-001", legacy=True), q("DA-002", legacy=True)]
        self.write_bank(items)
        self.assertIn(state._pick(items, self.hist())["id"], {"DA-001", "DA-002"})

    # 9 seen_count 只数仍在题库里的题
    def test_09_seen_count(self):
        items = [q("AGT-F001"), q("AGT-F002"), q("AGT-F003")]
        self.write_bank(items)
        h = self.hist(studied=[("AGT-F001", d(1)), ("AGT-F002", d(2)),
                               ("OLD-001", d(3)), ("OLD-002", d(4)), ("OLD-003", d(5))])
        self.assertEqual(state.seen_count(h), 2)

    # 10 同一天多次调用返回同一道题
    def test_10_stable_today(self):
        items = [q(f"AGT-F00{i}") for i in range(1, 8)]
        self.write_bank(items)
        h = self.hist()
        first = state.today_question(h, state.bank())["id"]
        for _ in range(5):
            self.assertEqual(state.today_question(state.load(), state.bank())["id"], first)

    # 附加：读取 exe 写出的 v2 文件（含 domain、CRLF）
    def test_11_load_v2_file(self):
        items = [q("AGT-F001"), q("AGT-X001", "X", ["AGT-F001"])]
        text = json.dumps({"category": "智能体与工具", "category_en": "Agents", "domain": "AGT",
                           "items": items}, ensure_ascii=False, indent=2).replace("\n", "\r\n")
        with open(os.path.join(self.bank, "04_agents.json"), "w", encoding="utf-8", newline="") as f:
            f.write(text)
        got = daily.load_bank()
        self.assertEqual([i["id"] for i in got], ["AGT-F001", "AGT-X001"])
        self.assertEqual(state.prereq_titles(got[1], got), [("AGT-F001", "题目 AGT-F001")])


if __name__ == "__main__":
    unittest.main()
