# -*- coding: utf-8 -*-
"""一天多题、记住才解锁、凌晨 4 点换日、安全写入的验收用例。全部用临时目录，不碰真实数据。

运行：在项目目录执行  python -m unittest discover -s tests -v
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import daily  # noqa: E402
from ui import state  # noqa: E402


def d(n):
    return (daily.logical_date() - dt.timedelta(days=n)).isoformat()


def q(qid, level="F", prereq=None, added=None):
    return {"id": qid, "difficulty": "中等", "tags": ["t"], "q_cn": "题目 " + qid, "q_en": "Q?",
            "a_en": "a", "a_cn": "b", "key_phrases": [], "approach": "c", "tips": "d",
            "level": level, "kind": "knowledge", "concepts": ["x.y"],
            "prereq": prereq or [], "added": added or d(60)}


class Base(unittest.TestCase):
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
        return state.bank()

    def passed(self, qid, day, reps=1):
        return {qid: {"level": 1, "due": d(-3), "reps": reps, "last_grade": 4}}


class UnlockTest(Base):
    # 1 前置题点了「没记住」→ 拓展题不解锁
    def test_01_failed_prereq_keeps_locked(self):
        items = self.write_bank([q("AGT-F001"), q("AGT-X001", "X", ["AGT-F001"])])
        h = state.load()
        h["study"]["days"][d(2)] = ["AGT-F001"]
        h["srs"] = {"AGT-F001": {"level": 0, "due": d(-5), "reps": 1, "last_grade": 1}}
        due, open_items, unseen = state._pools(items, h)
        self.assertEqual([i["id"] for i in open_items], [])
        self.assertEqual([i["id"] for i in unseen], ["AGT-X001"])

    # 2 今天才学会的基础题，今天不解锁它后面的拓展题；明天解锁
    def test_02_learned_today_unlocks_tomorrow(self):
        items = self.write_bank([q("AGT-F001"), q("AGT-X001", "X", ["AGT-F001"])])
        h = state.load()
        state.grade(h, "AGT-F001", 4)
        self.assertEqual(state._pools(items, state.load())[1], [])
        tomorrow = dt.datetime.now() + dt.timedelta(days=1)
        with mock.patch.object(daily, "logical_date", lambda now=None: tomorrow.date()):
            self.assertEqual([i["id"] for i in state._pools(items, state.load())[1]], ["AGT-X001"])

    # 3 早就学会的基础题今天复习通过 → 拓展题照常解锁
    def test_03_review_passed_today_still_unlocks(self):
        items = self.write_bank([q("AGT-F001"), q("AGT-X001", "X", ["AGT-F001"])])
        h = state.load()
        h["study"]["days"][d(5)] = ["AGT-F001"]
        h["srs"] = {"AGT-F001": {"level": 1, "due": d(0), "reps": 1, "last_grade": 4}}
        state.save(h)
        h = state.load()
        state.grade(h, "AGT-F001", 4)                 # 今天复习，通过
        self.assertEqual([i["id"] for i in state._pools(items, state.load())[1]], ["AGT-X001"])


class MultiTest(Base):
    # 4 第一题练完后给下一题，且不重复今天练过的
    def test_04_next_question_differs(self):
        items = self.write_bank([q(f"AGT-F00{i}") for i in range(1, 6)])
        h = state.load()
        first, why = state.current_question(h, items)
        self.assertIsNone(why)
        state.grade(h, first["id"], 4)
        seen = {first["id"]}
        for _ in range(2):
            h = state.load()
            nxt, why = state.current_question(h, items)
            self.assertIsNone(why)
            self.assertNotIn(nxt["id"], seen)
            # 没练完之前反复问，都是同一道
            self.assertEqual(state.current_question(state.load(), items)[0]["id"], nxt["id"])
            state.grade(h, nxt["id"], 4)
            seen.add(nxt["id"])

    # 5 点了「没记住」的题今天不再出现
    def test_05_failed_today_not_repeated(self):
        items = self.write_bank([q("AGT-F001"), q("AGT-F002")])
        h = state.load()
        first, _ = state.current_question(h, items)
        state.grade(h, first["id"], 1)
        h = state.load()
        nxt, _ = state.current_question(h, items)
        self.assertNotEqual(nxt["id"], first["id"])
        state.grade(h, nxt["id"], 1)
        self.assertEqual(state.current_question(state.load(), items), (None, "empty"))

    # 6 每日新题上限
    def test_06_new_cap(self):
        items = self.write_bank([q(f"AGT-F00{i}") for i in range(1, 9)])
        daily.save_settings({"new_per_day": 2})
        for n in range(2):
            h = state.load()
            it, why = state.current_question(h, items)
            self.assertIsNone(why)
            state.grade(h, it["id"], 4)
        self.assertEqual(state.current_question(state.load(), items), (None, "cap"))

    # 7 新题到了上限，到期复习题仍然可以练
    def test_07_reviews_ignore_new_cap(self):
        items = self.write_bank([q(f"AGT-F00{i}") for i in range(1, 6)])
        daily.save_settings({"new_per_day": 1})
        h = state.load()
        h["study"]["days"][d(3)] = ["AGT-F005"]
        h["srs"] = {"AGT-F005": {"level": 0, "due": d(0), "reps": 1, "last_grade": 1}}
        state.save(h)
        h = state.load()
        it, _ = state.current_question(h, items)
        self.assertEqual(it["id"], "AGT-F005")        # 复习优先
        state.grade(h, it["id"], 4)
        h = state.load()
        it, _ = state.current_question(h, items)      # 一道新题
        state.grade(h, it["id"], 4)
        self.assertEqual(state.current_question(state.load(), items), (None, "cap"))

    # 8 剩下的新题都被今天学的基础题卡着 → 贪多嚼不烂
    def test_08_blocked_by_todays_prereqs(self):
        items = self.write_bank([q("AGT-F001"), q("AGT-X001", "X", ["AGT-F001"]),
                                 q("AGT-X002", "X", ["AGT-X001"])])
        h = state.load()
        it, _ = state.current_question(h, items)
        self.assertEqual(it["id"], "AGT-F001")
        state.grade(h, it["id"], 4)
        got = state.current_question(state.load(), items)
        self.assertEqual(got, (None, "blocked"))
        self.assertEqual(state.NO_MORE[got[1]], "贪多嚼不烂，夯实基础下次继续")

    # 9 每天总题数上限
    def test_09_max_per_day(self):
        items = self.write_bank([q(f"AGT-F00{i}") for i in range(1, 9)])
        daily.save_settings({"max_per_day": 1, "new_per_day": 5})
        h = state.load()
        it, _ = state.current_question(h, items)
        state.grade(h, it["id"], 4)
        self.assertEqual(state.current_question(state.load(), items), (None, "max"))

    # 10 peek 不写记录
    def test_10_peek_does_not_save(self):
        items = self.write_bank([q(f"AGT-F00{i}") for i in range(1, 6)])
        h = state.load()
        it, _ = state.current_question(h, items)
        state.grade(h, it["id"], 4)
        h = state.load()
        nxt, _ = state.current_question(h, items, peek=True)
        self.assertIsNotNone(nxt)
        self.assertNotIn("current", state.load()["nudge"])

    # 11 今天到此为止
    def test_11_stop_today(self):
        self.write_bank([q("AGT-F001")])
        h = state.load()
        self.assertFalse(state.stopped_today(h))
        state.stop_today(h)
        self.assertTrue(state.stopped_today(state.load()))
        self.assertFalse(state.skipped_today(state.load()))


class DayBoundaryTest(Base):
    # 12 凌晨 4 点前算前一天
    def test_12_before_four_is_yesterday(self):
        self.assertEqual(daily.logical_date(dt.datetime(2026, 11, 20, 0, 30)), dt.date(2026, 11, 19))
        self.assertEqual(daily.logical_date(dt.datetime(2026, 11, 20, 3, 59)), dt.date(2026, 11, 19))
        self.assertEqual(daily.logical_date(dt.datetime(2026, 11, 20, 4, 0)), dt.date(2026, 11, 20))

    # 13 换日时间可以改回零点
    def test_13_day_start_setting(self):
        daily.save_settings({"day_start_hour": 0})
        self.assertEqual(daily.logical_date(dt.datetime(2026, 11, 20, 0, 30)), dt.date(2026, 11, 20))

    # 14 设置：不合法的值退回默认，文件损坏不报错
    def test_14_settings_validation(self):
        os.makedirs(daily.DATA_DIR, exist_ok=True)
        with open(daily.settings_path(), "w", encoding="utf-8") as f:
            json.dump({"mode": "weird", "new_per_day": -3, "interval_min": 45, "x": 1}, f)
        cfg = daily.settings()
        self.assertEqual((cfg["mode"], cfg["new_per_day"], cfg["interval_min"]), ("single", 3, 45))
        with open(daily.settings_path(), "w", encoding="utf-8") as f:
            f.write("{oops")
        self.assertEqual(daily.settings(), daily.SETTINGS_DEFAULT)


    # 14b 紧挨着的两次写入落在同一个时间戳里（时间戳很粗的文件系统），也要读到新内容
    def test_14b_same_timestamp_still_reloads(self):
        os.makedirs(daily.DATA_DIR, exist_ok=True)
        path = daily.settings_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"interval_min": 45}, f)
        os.utime(path, ns=(10 ** 18, 10 ** 18))
        self.assertEqual(daily.settings()["interval_min"], 45)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"interval_min": 120}, f)
        os.utime(path, ns=(10 ** 18, 10 ** 18))       # 修改时间和上一次完全一样
        self.assertEqual(daily.settings()["interval_min"], 120)
        daily.save_settings({"interval_min": 30})
        os.utime(path, ns=(10 ** 18, 10 ** 18))
        daily.save_settings({"interval_min": 90})
        os.utime(path, ns=(10 ** 18, 10 ** 18))
        self.assertEqual(daily.settings()["interval_min"], 90)


class SafeWriteTest(Base):
    # 15 保存不留临时文件；当天第一次保存前先备份
    def test_15_atomic_and_backup(self):
        self.write_bank([q("AGT-F001")])
        h = state.load()
        h["marker"] = 1
        state.save(h)
        self.assertEqual(sorted(os.listdir(daily.DATA_DIR)), ["history.json"])   # 第一次：还没有可备份的
        daily._backed_up = None                       # 模拟第二天 / 进程重启
        h["marker"] = 2
        state.save(h)
        baks = os.listdir(daily.backup_dir())
        self.assertEqual(len(baks), 1)
        with open(os.path.join(daily.backup_dir(), baks[0]), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["marker"], 1)
        self.assertFalse(os.path.exists(daily.HISTORY + ".tmp"))

    # 16 学习记录损坏时从备份恢复，坏文件留底
    def test_16_restore_from_backup(self):
        self.write_bank([q("AGT-F001")])
        h = state.load()
        h["marker"] = "good"
        state.save(h)
        daily._backed_up = None
        state.save(h)
        with open(daily.HISTORY, "w", encoding="utf-8") as f:
            f.write('{"drawn": {"x"')                 # 写到一半
        got = state.load()
        self.assertEqual(got["marker"], "good")
        self.assertTrue(any(n.startswith("history.corrupt-") for n in os.listdir(daily.DATA_DIR)))

    # 17 没有备份可用时原样报错，不拿空记录覆盖
    def test_17_corrupt_without_backup_raises(self):
        os.makedirs(daily.DATA_DIR, exist_ok=True)
        with open(daily.HISTORY, "w", encoding="utf-8") as f:
            f.write("{broken")
        with self.assertRaises(ValueError):
            state.load()
        with open(daily.HISTORY, encoding="utf-8") as f:
            self.assertEqual(f.read(), "{broken")

    # 18 计时状态存在 runtime.json，不写学习记录
    def test_18_runtime_separate(self):
        state.runtime_update(active=120, need=600)
        self.assertEqual(state.runtime_load()["active"], 120)
        self.assertFalse(os.path.exists(daily.HISTORY))

    # 19 打分时带上用时等信息，写进行为日志
    def test_19_done_event_meta(self):
        self.write_bank([q("AGT-F001")])
        h = state.load()
        state.grade(h, "AGT-F001", 4, secs=95, spoke=True, mode="session")
        ev = state.load()["study"]["events"][-1]
        self.assertEqual((ev["type"], ev["secs"], ev["spoke"], ev["mode"]), ("done", 95, True, "session"))


if __name__ == "__main__":
    unittest.main()
