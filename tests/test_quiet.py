# -*- coding: utf-8 -*-
"""勿扰（全屏 / 通话时不弹提醒）的验收用例。全部用临时数据，不碰真实学习记录。

运行：在 面试英语题库 目录执行  python -m unittest discover -s tests -v
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
from ui import quiet  # noqa: E402


def load_app():
    loader = importlib.machinery.SourceFileLoader("app_under_test", os.path.join(ROOT, "app.pyw"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class FakePopup:
    def __init__(self):
        self.withdrawn = False

    def withdraw_quiet(self):
        self.withdrawn = True


class QuietDaemonTest(unittest.TestCase):
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
            json.dump({"category": "测试", "category_en": "T", "domain": "TST", "items": [
                {"id": "TST-F001", "level": "F", "q_cn": "题", "q_en": "Q?", "a_en": "a", "a_cn": "b",
                 "difficulty": "中等", "tags": [], "key_phrases": [], "approach": "", "tips": ""}]}, f)
        cfg = os.path.join(self.tmp, "题库路径.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"bank_dir": bank}, f)
        self._saved = (daily.BANK_CONFIG, daily.HISTORY, daily.DATA_DIR)
        daily.BANK_CONFIG = cfg
        daily.DATA_DIR = os.path.join(self.tmp, "data")
        daily.HISTORY = os.path.join(daily.DATA_DIR, "history.json")
        self.app = load_app()
        self.app.LOG = os.path.join(self.tmp, "nudge.log")
        self.shown = 0
        self.clock = [1000.0]
        self.reason = [None]
        self.patches = [
            mock.patch.object(quiet, "busy_reason", lambda *a, **k: self.reason[0]),
            mock.patch.object(self.app.Daemon, "show", lambda daemon: self._count_show()),
            mock.patch.object(self.app, "idle_seconds", lambda: 0.0),
            mock.patch.object(self.app.time, "monotonic", lambda: self.clock[0]),
        ]
        for p in self.patches:
            p.start()
        self.d = self.app.Daemon(self.root)
        self.d.active = 10 ** 6                       # 已满足弹出时间
        self.shown = 0

    def _count_show(self):
        self.shown += 1

    def tearDown(self):
        for p in getattr(self, "patches", []):
            p.stop()
        if hasattr(self, "_saved"):
            daily.BANK_CONFIG, daily.HISTORY, daily.DATA_DIR = self._saved
        if hasattr(self, "root"):
            self.root.destroy()
        shutil.rmtree(getattr(self, "tmp", ""), ignore_errors=True)

    # 1 全屏 / 通话时不弹
    def test_01_busy_blocks_popup(self):
        self.reason[0] = "有全屏程序正在运行"
        self.d._tick()
        self.assertEqual(self.shown, 0)

    # 2 没有勿扰时正常弹出
    def test_02_free_shows(self):
        self.d._tick()
        self.assertEqual(self.shown, 1)

    # 3 勿扰解除后先等 2 分钟
    def test_03_grace_after_busy(self):
        self.reason[0] = "麦克风正在使用（Zoom.exe）"
        self.d._tick()
        self.reason[0] = None
        self.clock[0] += 15
        self.d._tick()
        self.assertEqual(self.shown, 0, "刚解除不应立刻弹出")
        self.clock[0] += self.app.QUIET_GRACE
        self.d._tick()
        self.assertEqual(self.shown, 1)

    # 4 已弹出的提醒遇到全屏会被悄悄收起，且不记为稍后/休息
    def test_04_withdraw_visible_popup(self):
        popup = FakePopup()
        self.d.popup = popup
        self.reason[0] = "前台窗口全屏（在线笔试）"
        self.d._tick()
        self.assertTrue(popup.withdrawn)
        self.assertIsNone(self.d.popup)
        h = self.d.state.load()
        self.assertNotEqual(h["nudge"]["last_prompt"], "skip:" + self.d.state.today())
        self.assertEqual(self.shown, 0)

    # 5 检测出错时不影响提醒
    def test_05_check_error_is_ignored(self):
        def boom(*a, **k):
            raise RuntimeError("x")
        with mock.patch.object(quiet, "busy_reason", boom):
            self.d._tick()
        self.assertEqual(self.shown, 1)


class QuietModuleTest(unittest.TestCase):
    # 6 三道检查都能被调用且不抛异常；非 Windows 上一律返回 None
    def test_06_checks_safe(self):
        for f in (quiet.notification_state, quiet.foreground_fullscreen, quiet.capture_in_use):
            r = f()
            self.assertTrue(r is None or isinstance(r, str))
        if os.name != "nt":
            self.assertIsNone(quiet.busy_reason())


if __name__ == "__main__":
    unittest.main()
