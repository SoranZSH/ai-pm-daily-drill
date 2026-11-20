# -*- coding: utf-8 -*-
"""守护进程的提醒节奏：提醒时机、稍后 / 没人理、多题提醒、练习窗口被晾、暂停。
全部用临时数据，不碰真实学习记录；弹窗和练习窗口用替身，不真的弹出来。

运行：在项目目录执行  python -m unittest discover -s tests -v
"""
import importlib.machinery
import importlib.util
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
from ui import quiet, state  # noqa: E402


def load_app():
    loader = importlib.machinery.SourceFileLoader("app_flow_test", os.path.join(ROOT, "app.pyw"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def q(qid, prereq=None):
    return {"id": qid, "level": "F", "q_cn": "题 " + qid, "q_en": "Q?", "a_en": "a", "a_cn": "b",
            "difficulty": "中等", "tags": [], "key_phrases": [], "approach": "", "tips": "",
            "prereq": prereq or []}


class FakePractice:
    def __init__(self, item=None, graded=(), fg=False):
        self.item = item or q("TST-F001")
        self.graded = list(graded)
        self.stopped = False
        self.fg = fg
        self.ended = self.fronted = False

    def is_foreground(self):
        return self.fg

    def bring_front(self):
        self.fronted = True

    def _end(self):
        self.ended = True


class FlowTest(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
            self.root = tk.Tk()
            self.root.withdraw()
        except Exception as e:                      # 没有图形界面的环境
            self.skipTest(f"无法创建窗口：{e}")
        self.tmp = tempfile.mkdtemp()
        bank = os.path.join(self.tmp, "bank")
        os.makedirs(bank)
        with open(os.path.join(bank, "01.json"), "w", encoding="utf-8") as f:
            json.dump({"category": "测试", "category_en": "T", "domain": "TST",
                       "items": [q(f"TST-F00{i}") for i in range(1, 7)]}, f)
        cfg = os.path.join(self.tmp, "题库路径.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"bank_dir": bank}, f)
        self._saved = (daily.BANK_CONFIG, daily.HISTORY, daily.DATA_DIR)
        daily.BANK_CONFIG = cfg
        daily.DATA_DIR = os.path.join(self.tmp, "data")
        daily.HISTORY = os.path.join(daily.DATA_DIR, "history.json")
        self.app = load_app()
        self.app.LOG = os.path.join(self.tmp, "nudge.log")
        self.shown = []
        self.clock = [1000.0]
        self.idle = [0.0]
        self.patches = [
            mock.patch.object(quiet, "busy_reason", lambda *a, **k: None),
            mock.patch.object(self.app.Daemon, "show",
                              lambda daemon, kind="first": self.shown.append(kind)),
            mock.patch.object(self.app, "idle_seconds", lambda: self.idle[0]),
            mock.patch.object(self.app.time, "monotonic", lambda: self.clock[0]),
        ]
        for p in self.patches:
            p.start()
        self.d = self.app.Daemon(self.root)

    def tearDown(self):
        for p in getattr(self, "patches", []):
            p.stop()
        if hasattr(self, "_saved"):
            daily.BANK_CONFIG, daily.HISTORY, daily.DATA_DIR = self._saved
        if hasattr(self, "root"):
            self.root.destroy()
        shutil.rmtree(getattr(self, "tmp", ""), ignore_errors=True)

    def ticks(self, n, idle=0.0):
        """模拟 n 个主循环周期，每个周期 TICK 秒。"""
        self.idle[0] = idle
        for _ in range(n):
            self.clock[0] += self.app.TICK
            self.d._tick()

    def minutes(self, m, idle=0.0):
        self.ticks(int(m * 60 / self.app.TICK), idle)

    # 1 刚开机不提醒：先让人用一会儿电脑（默认 10 分钟）
    def test_01_warmup_before_first_nudge(self):
        self.minutes(9)
        self.assertEqual(self.shown, [])

    # 2 用够了时间也不在做事中途打断：等「离开一会儿又回来」的那一刻
    def test_02_waits_for_return_moment(self):
        self.minutes(12)
        self.assertEqual(self.shown, [], "一直在用电脑，不该中途打断")
        self.ticks(10, idle=300)                     # 离开了几分钟
        self.assertEqual(self.shown, [])
        self.ticks(1)                                # 回来了
        self.assertEqual(self.shown, ["first"])

    # 3 一直等不到空当，最多再等 30 分钟活跃时间就提醒
    def test_03_patience_runs_out(self):
        self.minutes(10 + 29)
        self.assertEqual(self.shown, [])
        self.minutes(2)
        self.assertEqual(self.shown[:1], ["first"])    # 替身不会占住弹窗位，之后每个周期都会再记一次

    # 4 没人理自动收起 → 25 分钟后再试；点了稍后 → 等完整间隔
    def test_04_timeout_retries_sooner_than_later(self):
        self.d.popup_kind = "first"
        self.d.on_snooze("timeout")
        self.assertEqual(self.d.need, 25 * 60)
        self.d.on_snooze("later")
        self.assertEqual(self.d.need, 60 * 60)
        self.assertEqual(self.d.active, 0)
        rt = state.runtime_load()
        self.assertEqual((rt["need"], rt["day"]), (60 * 60, state.today()))

    # 5 每天一题：学过之后今天不再提醒
    def test_05_single_mode_done_is_done(self):
        h = state.load()
        state.grade(h, "TST-F001", 4)
        self.d._wait(0)
        self.minutes(50)
        self.assertEqual(self.shown, [])

    # 6 多题提醒：学过之后隔一个间隔提醒下一题
    def test_06_multi_mode_nudges_next(self):
        daily.save_settings({"mode": "multi"})
        h = state.load()
        state.grade(h, "TST-F001", 4)
        self.d.practice = FakePractice(graded=[("TST-F001", 4)])
        self.d.on_practice_closed()
        self.assertEqual(self.d.need, 60 * 60)
        self.minutes(59)
        self.assertEqual(self.shown, [])
        self.ticks(8, idle=300)
        self.minutes(2)
        self.assertEqual(set(self.shown), {"next"})

    # 7 多题提醒：今天到此为止 / 到了上限就不再提醒
    def test_07_multi_mode_stops(self):
        daily.save_settings({"mode": "multi", "new_per_day": 1})
        h = state.load()
        state.grade(h, "TST-F001", 4)
        self.d._wait(0)
        self.minutes(45)
        self.assertEqual(self.shown, [], "新题到了上限，没有可学的题")
        self.assertEqual(self.d.no_more, "cap")
        daily.save_settings({"new_per_day": 3})
        self.d._settings_saved()
        self.d.on_stop()
        self.minutes(45)
        self.assertEqual(self.shown, [], "已经说了今天到此为止")

    # 8 练习窗口开着没做完、被晾了 20 分钟 → 再提醒一次；在前台时不提醒
    def test_08_resume_reminder(self):
        p = self.d.practice = FakePractice(fg=True)
        self.minutes(30)
        self.assertEqual(self.shown, [])
        p.fg = False
        self.minutes(19)
        self.assertEqual(self.shown, [])
        self.minutes(2)
        self.assertEqual(self.shown[0], "resume")

    # 9 没做完就关掉不算学习，按稍后处理；做完的按间隔继续
    def test_09_closed_unfinished_is_snooze(self):
        self.d.practice = FakePractice()
        self.d.on_practice_closed()
        self.assertIsNone(self.d.practice)
        self.assertEqual(self.d.need, 60 * 60)
        self.assertFalse(state.done_today(state.load()))

    # 10 跨天时收起没做完的旧练习窗口，并重新开始计时
    def test_10_new_day_closes_stale_window(self):
        p = self.d.practice = FakePractice()
        self.d.day = "2000-01-01"
        self.ticks(1)
        self.assertTrue(p.ended)
        self.assertEqual(self.d.day, state.today())
        self.assertEqual(self.d.need, 10 * 60)

    # 11 暂停提醒期间不弹；托盘「现在学一题」在练习窗口已开时只是把它拉到眼前
    def test_11_pause_and_tray_practice(self):
        self.d._command("pause")
        self.assertTrue(self.d._paused())
        self.minutes(60)
        self.assertEqual(self.shown, [])
        self.d._command("pause")
        self.assertFalse(self.d._paused())
        p = self.d.practice = FakePractice()
        self.d._command("practice")
        self.assertTrue(p.fronted)

    # 12 托盘菜单内容随状态变化
    def test_12_tray_menu(self):
        h = state.load()
        state.grade(h, "TST-F001", 4)
        self.d._status(state.load())
        labels = [e[1] for e in self.d.menu_cache if e]
        self.assertIn("现在学一题", labels)
        self.assertIn("暂停提醒 2 小时", labels)
        self.assertTrue(any(s.startswith("今天已学 1 题") for s in labels))
        self.assertIn("今天已学 1 题", self.d.tip)

    # 13 今天在托盘点了退出：记下日期，守护任务拉起时据此不再启动
    def test_13_quit_marks_today(self):
        self.d.quit()
        self.assertEqual(state.runtime_load()["quit_day"], state.today())


if __name__ == "__main__":
    unittest.main()
