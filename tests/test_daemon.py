# -*- coding: utf-8 -*-
"""守护进程的纯逻辑：空闲时间计算、看门狗卡死判定。"""
import importlib.machinery
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader("app_daemon", os.path.join(HERE, "..", "app.pyw"))
_spec = importlib.util.spec_from_loader("app_daemon", _loader)
app = importlib.util.module_from_spec(_spec)
_loader.exec_module(app)


class IdleTest(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(app.idle_from(10_000, 4_000), 6.0)

    def test_wraparound(self):
        # 32 位计数在 49.7 天回绕：当前计数已回到很小，上次输入在回绕前
        self.assertAlmostEqual(app.idle_from(1_000, 0xFFFFFFFF - 999), 2.0)

    def test_high_uptime_not_zero(self):
        # 开机 30 天（计数超过 2^31）时旧代码会得到负数再被截成 0
        base = 30 * 24 * 3600 * 1000 & 0xFFFFFFFF
        self.assertEqual(app.idle_from(base, base - 300_000), 300.0)


class WatchdogTest(unittest.TestCase):
    def test_healthy(self):
        stuck, beat = app.hung(now=1000, last_check=970, last_beat=990)
        self.assertFalse(stuck)
        self.assertEqual(beat, 990)

    def test_stuck(self):
        stuck, _ = app.hung(now=1000, last_check=970, last_beat=1000 - app.HANG_LIMIT - 1)
        self.assertTrue(stuck)

    def test_resume_from_sleep_not_stuck(self):
        # 电脑睡了 8 小时：看门狗自己也停了很久，唤醒后第一次检查不能误判
        stuck, beat = app.hung(now=30000, last_check=1000, last_beat=990)
        self.assertFalse(stuck)
        self.assertEqual(beat, 30000)
        # 唤醒后主循环正常跳动，下一次检查依然健康
        stuck, _ = app.hung(now=30030, last_check=30000, last_beat=30020)
        self.assertFalse(stuck)


if __name__ == "__main__":
    unittest.main()
