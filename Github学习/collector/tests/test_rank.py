"""第 2 步（M4.3、M4.4）：rank.py 的单元测试（离线）。对应 M4 验收用例 4、5、7。"""
import math
import os
import statistics
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import rank  # noqa: E402

DAYS = 8


def cfg(min_samples=30, min_gain=20, min_heat=1.0, share=0.3):
    return {"min_gain_window": min_gain,
            "heat": {"baseline_days": 60, "min_group_samples": min_samples, "min_heat_score": min_heat},
            "languages": {"min_non_english_share": share}}


def hist(group, gains, days=DAYS):
    return [{"lang_group": group, "gain": g, "days": days} for g in gains]


def cand(rid, group, gain, days=DAYS, heat=None):
    return {"repo_id": rid, "lang_group": group, "gain": gain, "days": days, "heat": heat, "ref": rid}


class HeatTest(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.log = lambda lv, m: self.logs.append(m)

    def test_cold_start_when_merged_samples_below_minimum(self):
        rows = [cand(1, "en", 100), cand(2, "zh", 50)]
        heat, cold = rank.compute_heat(rows, hist("en", [100]) + hist("zh", [50]), cfg(), self.log)
        self.assertTrue(cold)
        self.assertEqual(heat, {1: None, 2: None})
        self.assertTrue(any("冷启动：热度分未启用" in m for m in self.logs))

    def test_formula_matches_hand_calculation(self):
        gains = [40, 60, 80, 100, 120, 160, 200] * 5          # 35 个英语样本
        base = hist("en", gains)
        rows = [cand(9, "en", 120)]
        heat, cold = rank.compute_heat(rows, base, cfg(), self.log)
        self.assertFalse(cold)
        xs = [math.log(1 + g / DAYS) for g in gains]
        m = statistics.median(xs)
        s = max(statistics.median([abs(x - m) for x in xs]), rank.MAD_FLOOR)
        expected = (math.log(1 + 120 / DAYS) - m) / (1.4826 * s)
        self.assertAlmostEqual(heat[9], expected, places=9)

    def test_mad_floor_applied_when_spread_is_zero(self):
        base = hist("en", [80] * 40)                           # 所有样本相同 → MAD=0 → 取 0.25
        heat, _ = rank.compute_heat([cand(9, "en", 160)], base, cfg(), self.log)
        expected = (math.log(1 + 160 / DAYS) - math.log(1 + 80 / DAYS)) / (1.4826 * 0.25)
        self.assertAlmostEqual(heat[9], expected, places=9)

    def test_small_group_falls_back_to_merged_baseline_and_logs(self):
        # 验收用例 5：中文组历史只有 5 条 → 合并基线（样本够），日志写明
        base = hist("en", [40, 60, 80, 100, 120] * 6) + hist("zh", [30, 40, 50, 60, 70])
        rows = [cand(7, "zh", 200)]
        heat, cold = rank.compute_heat(rows, base, cfg(), self.log)
        self.assertFalse(cold)
        self.assertIsNotNone(heat[7])
        self.assertTrue(any("语言组 zh 历史样本 5 < 30，改用合并基线" in m for m in self.logs))

    def test_prominent_chinese_projects_outrank_most_english(self):
        # 验收用例 4：英语组 10 个中等偏高；中文组历史足够（30 条，较低）、本次 3 个在组内很突出
        en_hist = hist("en", [40, 60, 80, 100, 120] * 8)                    # 40 条
        zh_hist = hist("zh", [8, 10, 12, 9, 11, 10, 8, 12, 9, 10] * 3)     # 30 条，每天约 1–1.5 颗
        en_now = [cand(i, "en", g) for i, g in enumerate([100, 110, 120, 130, 140, 150, 90, 95, 105, 115])]
        zh_now = [cand(100 + i, "zh", g) for i, g in enumerate([80, 90, 100])]     # 每天 10–12.5 颗
        heat, cold = rank.compute_heat(en_now + zh_now, en_hist + zh_hist, cfg(), self.log)
        self.assertFalse(cold)
        en_heats = [heat[c["repo_id"]] for c in en_now]
        for c in zh_now:
            beaten = sum(1 for h in en_heats if heat[c["repo_id"]] > h)
            self.assertGreaterEqual(beaten, 7, f"中文项目只超过 {beaten} 个英语项目")


class SelectTest(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.log = lambda lv, m: self.logs.append(m)

    def test_cold_start_orders_by_gain_per_day_and_skips_heat_threshold(self):
        c = cfg()
        cands = [cand(1, "en", 100, heat=None), cand(2, "en", 50, heat=None), cand(3, "en", 10, heat=None)]
        picked = rank.select(cands, c, 10, True, self.log)
        self.assertEqual([v["repo_id"] for v in picked], [1, 2])          # 3 的 gain 低于 min_gain_window=20

    def test_heat_threshold_filters_when_not_cold(self):
        c = cfg()
        cands = [cand(1, "en", 100, heat=2.0), cand(2, "en", 100, heat=0.5), cand(3, "en", 100, heat=1.0)]
        picked = rank.select(cands, c, 10, False, self.log)
        self.assertEqual([v["repo_id"] for v in picked], [1, 3])

    def test_limit_respected(self):
        cands = [cand(i, "en", 100, heat=10 - i) for i in range(6)]
        picked = rank.select(cands, cfg(), 3, False, self.log)
        self.assertEqual([v["repo_id"] for v in picked], [0, 1, 2])

    def test_quota_replaces_lowest_english_with_best_non_english(self):
        # 10 个入选名额，英语 10 个都高于非英语；要求非英语 ≥ ceil(0.3×10)=3 → 替换 3 个英语
        en = [cand(i, "en", 100, heat=5 - i * 0.1) for i in range(10)]
        non = [cand(100 + i, "zh", 100, heat=2.0 - i * 0.1) for i in range(4)]
        picked = rank.select(en + non, cfg(), 10, False, self.log)
        non_in = [v for v in picked if v["lang_group"] != "en"]
        self.assertEqual(len(non_in), 3)
        self.assertEqual(len(picked), 10)
        self.assertEqual([v["repo_id"] for v in non_in], [100, 101, 102])
        self.assertTrue(any("用 3 个非英语项目替换英语项目" in m for m in self.logs))

    def test_quota_not_forced_when_no_eligible_non_english(self):
        # 验收用例 7：所有非英语候选都不合格 → 不强行凑配额
        en = [cand(i, "en", 100, heat=3.0) for i in range(5)]
        non = [cand(100, "zh", 100, heat=0.2), cand(101, "ja", 5, heat=5.0)]   # 0.2 热度不足；5 增长不足
        picked = rank.select(en + non, cfg(), 10, False, self.log)
        self.assertEqual(len(picked), 5)
        self.assertTrue(all(v["lang_group"] == "en" for v in picked))
        self.assertTrue(any("非英语合格候选只有 0 个，未达配额 2 个，不强行补足" in m for m in self.logs))

    def test_ceiling_avoids_float_error(self):
        # 0.3 × 10 = 3.0000000000000004：必须按 3 个计算，不能因浮点误差变成 4 个
        en = [cand(i, "en", 100, heat=5 - i * 0.1) for i in range(10)]
        non = [cand(100 + i, "zh", 100, heat=2 - i * 0.1) for i in range(5)]
        picked = rank.select(en + non, cfg(), 10, False, self.log)
        self.assertEqual(sum(1 for v in picked if v["lang_group"] != "en"), 3)


def dcand(rid, group, gain, heat, direction, days=DAYS):
    c = cand(rid, group, gain, days=days, heat=heat)
    c["direction"] = direction
    return c


class DirectionCapTest(unittest.TestCase):
    """M5.2 同方向上限（per_direction_cap）：同一方向入包不超过上限；unclassified 不受限制；配额替换同样遵守上限。"""

    def setUp(self):
        self.logs = []
        self.log = lambda lv, m: self.logs.append(m)

    def capped(self, n=3):
        c = cfg()
        c["per_direction_cap"] = n
        return c

    def test_same_direction_never_exceeds_cap(self):
        cands = [dcand(i, "en", 100, 5 - i * 0.1, "rag") for i in range(5)]
        picked = rank.select(cands, self.capped(2), 10, False, self.log)
        self.assertEqual([v["repo_id"] for v in picked], [0, 1])
        self.assertTrue(any("同方向上限 2：跳过 3 个超出上限的候选" in m for m in self.logs))

    def test_cap_frees_slots_for_other_directions(self):
        cands = [dcand(0, "en", 100, 5.0, "rag"), dcand(1, "en", 100, 4.9, "rag"),
                 dcand(2, "en", 100, 4.8, "rag"), dcand(3, "en", 100, 4.0, "agent"),
                 dcand(4, "en", 100, 3.9, "agent")]
        picked = rank.select(cands, self.capped(2), 10, False, self.log)
        self.assertEqual(sorted(v["repo_id"] for v in picked), [0, 1, 3, 4])

    def test_unclassified_is_not_capped(self):
        cands = [dcand(i, "en", 100, 5 - i * 0.1, "unclassified") for i in range(5)]
        picked = rank.select(cands, self.capped(1), 10, False, self.log)
        self.assertEqual(len(picked), 5)

    def test_quota_replacement_respects_cap_and_uses_allowed_direction(self):
        # 英语 3 个均为 rag（已达上限 3）；非英语 rag 不可替换，非英语 agent 可以替换最低分的英语
        cands = [dcand(0, "en", 100, 5.0, "rag"), dcand(1, "en", 100, 4.9, "rag"),
                 dcand(2, "en", 100, 4.8, "rag"),
                 dcand(100, "zh", 100, 1.4, "rag"), dcand(101, "zh", 100, 1.5, "agent")]
        picked = rank.select(cands, self.capped(3), 3, False, self.log)
        ids = sorted(v["repo_id"] for v in picked)
        self.assertEqual(ids, [0, 1, 101])          # 2 号（最低分英语）被非英语 agent 替换
        self.assertNotIn(100, ids)                  # 非英语 rag 因上限不可入选
        self.assertTrue(any("用 1 个非英语项目替换英语项目" in m for m in self.logs))

    def test_quota_swap_within_same_direction_keeps_cap(self):
        # 替换发生在同一方向：释放英语的名额后，同方向非英语可占用，方向计数不超过上限
        cands = [dcand(0, "en", 100, 5.0, "rag"), dcand(1, "en", 100, 4.9, "rag"),
                 dcand(2, "en", 100, 4.8, "rag"), dcand(100, "zh", 100, 1.5, "rag")]
        picked = rank.select(cands, self.capped(3), 3, False, self.log)
        self.assertEqual(sorted(v["repo_id"] for v in picked), [0, 1, 100])
        self.assertTrue(any("用 1 个非英语项目替换英语项目" in m for m in self.logs))

    def test_quota_not_forced_past_cap(self):
        # 同方向 rag 已达上限 2；被替换的英语是 agent，释放它的名额不能让 rag 超限，所以非英语 rag 不入选
        cands = [dcand(0, "en", 100, 5.0, "rag"), dcand(1, "en", 100, 4.9, "rag"),
                 dcand(2, "en", 100, 4.0, "agent"), dcand(100, "zh", 100, 1.5, "rag")]
        picked = rank.select(cands, self.capped(2), 3, False, self.log)
        self.assertEqual(sorted(v["repo_id"] for v in picked), [0, 1, 2])
        self.assertNotIn(100, [v["repo_id"] for v in picked])
        self.assertTrue(any("非英语合格候选只有 0 个，未达配额 1 个，不强行补足" in m for m in self.logs))


if __name__ == "__main__":
    unittest.main()
