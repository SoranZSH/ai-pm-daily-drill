"""第 5 步（M5.1–M5.5）：classify.py 的单元测试（离线、纯计算）。

对应 M5 验收用例 1、2、3、4、5、8；另覆盖复收条件、相关题与差异证据的边界。
测试使用自带的小型方向表与知识地图，不读取真实的 方向词表.json 或 知识地图.json。
"""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import classify as cl  # noqa: E402

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 10, 3, 0, tzinfo=UTC)

DIRECTIONS = {
    "rag": {"domain": "RAG", "topics": ["rag"],
            "prerequisites": ["rag.vector_db", "rag.chunking"],
            "keywords": {"zh": ["检索增强"], "en": ["knowledge base"]}},
    "agent-framework": {"domain": "Agent", "topics": ["agent"],
                        "prerequisites": [],
                        "keywords": {"zh": ["智能体"], "en": ["multi-agent"]}},
}

CONCEPTS = {
    "rag.vector_db": {"name": "向量数据库", "aliases": ["vector database", "向量数据库"]},
    "rag.chunking": {"name": "文本切块", "aliases": ["chunking", "文本切块"]},
    "rag.rerank": {"name": "重排序", "aliases": ["rerank", "重排序"]},
}

CFG = {"revisit_min_days": 30}


class ClassifyTest(unittest.TestCase):
    def test_case1_topic_plus_keyword_is_rag_high(self):
        # 用例 1：topics=[rag]，描述含 knowledge base → rag，高置信
        r = cl.classify(DIRECTIONS, ["rag"], "own/a", "knowledge base for teams", "")
        self.assertEqual(r["direction"], "rag")
        self.assertEqual(r["direction_confidence"], "high")
        self.assertEqual(r["domain"], "RAG")

    def test_case2_chinese_keyword_gives_agent_framework_low_or_medium(self):
        # 用例 2：描述含「智能体」，无 topic → agent-framework，置信为低或中（此处命中一次，为低）
        r = cl.classify(DIRECTIONS, [], "own/b", "一个智能体工具包", "")
        self.assertEqual(r["direction"], "agent-framework")
        self.assertIn(r["direction_confidence"], ("low", "medium"))
        self.assertEqual(r["direction_confidence"], "low")

    def test_case3_no_hits_is_unclassified_with_null_domain(self):
        # 用例 3：没有任何命中 → unclassified，domain 为 null
        r = cl.classify(DIRECTIONS, ["unrelated"], "own/c", "a cooking recipe site", "")
        self.assertEqual(r["direction"], "unclassified")
        self.assertIsNone(r["domain"])
        self.assertEqual(r["secondary_directions"], [])

    def test_ties_follow_table_order(self):
        r = cl.classify(DIRECTIONS, [], "own/t", "knowledge base and 智能体", "")
        self.assertEqual(r["direction"], "rag")            # 两者各得 1 分，表中 rag 在前

    def test_secondary_needs_score_at_least_two(self):
        # rag：topic 命中 3 分；agent：两个关键词各 1 分，合计 2 分 → 进入次要方向
        r = cl.classify(DIRECTIONS, ["rag"], "own/s", "智能体 multi-agent", "")
        self.assertEqual(r["direction"], "rag")
        self.assertEqual(r["secondary_directions"], ["agent-framework"])

    def test_ascii_keyword_uses_word_boundary(self):
        # 短英文词按词边界匹配：关键词 ai 不应命中 email 中的子串
        dirs = {"x": {"domain": "D", "topics": [], "prerequisites": [],
                      "keywords": {"en": ["ai"]}}}
        self.assertEqual(cl.classify(dirs, [], "own/mail", "email client", "")["direction"], "unclassified")
        self.assertEqual(cl.classify(dirs, [], "own/ai", "an AI toolkit", "")["direction"], "x")

    def test_readme_only_counts_first_3000_chars(self):
        readme = "x" * 3000 + " knowledge base"
        r = cl.classify(DIRECTIONS, [], "own/r", "plain", readme)
        self.assertEqual(r["direction"], "unclassified")


class LearningModeTest(unittest.TestCase):
    PREREQS = ["rag.vector_db", "rag.chunking"]

    def test_case4_all_prerequisites_covered_gives_delta(self):
        m = cl.decide_mode("rag", self.PREREQS, {"rag.vector_db", "rag.chunking", "rag.rerank"}, CONCEPTS)
        self.assertEqual(m["learning_mode"], "delta")
        self.assertEqual(m["prerequisites_missing"], [])

    def test_case5_two_missing_gives_foundation_with_exact_list(self):
        m = cl.decide_mode("rag", self.PREREQS, set(), CONCEPTS)
        self.assertEqual(m["learning_mode"], "foundation")
        self.assertEqual(m["prerequisites_missing"],
                         [{"key": "rag.vector_db", "name": "向量数据库"},
                          {"key": "rag.chunking", "name": "文本切块"}])

    def test_unclassified_is_foundation_with_fixed_reason(self):
        m = cl.decide_mode("unclassified", [], set(), CONCEPTS)
        self.assertEqual(m["learning_mode"], "foundation")
        self.assertEqual(m["mode_reason"], "未识别到方向，按基础模式处理")

    def test_missing_concept_name_falls_back_to_key(self):
        m = cl.decide_mode("rag", ["rag.unknown"], set(), CONCEPTS)
        self.assertEqual(m["prerequisites_missing"], [{"key": "rag.unknown", "name": "rag.unknown"}])


class RevisitTest(unittest.TestCase):
    def row(self, **kw):
        base = {"status": "questioned", "questioned_at": "2026-09-05",
                "last_release_tag": "v1.0.0", "gain_at_first_pack": None}
        base.update(kw)
        return base

    def test_case6_35_days_and_new_major_gives_release_update(self):
        u = cl.update_reason(self.row(), NOW, CFG, "v2.0.0", 25)
        self.assertEqual(u["kind"], "release")
        self.assertEqual(u["text"], "发布触发：上次出题后发布了 v2")

    def test_case7_10_days_is_never_updated(self):
        self.assertIsNone(cl.update_reason(self.row(questioned_at="2026-09-30"), NOW, CFG, "v9.0.0", 999))

    def test_same_major_is_not_a_release_update(self):
        self.assertIsNone(cl.update_reason(self.row(), NOW, CFG, "v1.9.0", 5))

    def test_gain_rule_needs_recorded_first_pack_gain(self):
        self.assertIsNone(cl.update_reason(self.row(gain_at_first_pack=None), NOW, CFG, None, 500))
        # gain_at_first_pack 与比较值均为「日均新增」：基线 20/日，当前 40/日 → 达到 2 倍
        u = cl.update_reason(self.row(gain_at_first_pack=20), NOW, CFG, None, 40)
        self.assertEqual(u["kind"], "gain")
        self.assertTrue(u["text"].startswith("增长触发"))
        self.assertIsNone(cl.update_reason(self.row(gain_at_first_pack=20), NOW, CFG, None, 39))

    def test_missing_release_record_does_not_trigger_release_rule(self):
        self.assertIsNone(cl.update_reason(self.row(last_release_tag=None), NOW, CFG, "v2.0.0", 5))

    def test_major_version_parsing(self):
        self.assertEqual(cl.major_of("v2.0.0"), 2)
        self.assertEqual(cl.major_of("release-3"), 3)
        self.assertIsNone(cl.major_of(""))
        self.assertIsNone(cl.major_of(None))


class RelatedQuestionsTest(unittest.TestCase):
    def test_f_questions_first_and_capped_at_eight(self):
        items = [{"id": f"RAG-X{i:03d}", "level": "X", "concepts": ["rag.rerank"], "q_cn": f"x{i}"}
                 for i in range(5)]
        items += [{"id": f"RAG-F{i:03d}", "level": "F", "concepts": ["rag.rerank"], "q_cn": f"f{i}"}
                  for i in range(6)]
        items += [{"id": None, "level": "F", "concepts": ["rag.rerank"]}]          # 无题号，不计入
        got = cl.related_questions(items, {"rag.rerank"})
        self.assertEqual(len(got), 8)
        self.assertEqual([g["level"] for g in got[:6]], ["F"] * 6)
        self.assertTrue(all(g["id"] for g in got))

    def test_no_overlap_gives_empty(self):
        self.assertEqual(cl.related_questions([{"id": "A", "concepts": ["x"]}], {"y"}), [])


class ConceptHitTest(unittest.TestCase):
    def test_aliases_in_text_match_concepts(self):
        text = cl.build_text("own/a", "Vector database toolkit", [], "支持文本切块与重排序")
        self.assertEqual(cl.concept_hits(CONCEPTS, text), {"rag.vector_db", "rag.chunking", "rag.rerank"})


class DiffEvidenceTest(unittest.TestCase):
    def compared(self, deps, tree, rid="own/b", ids=("RAG-F001",)):
        return {"full_name": rid, "question_ids": list(ids), "dependencies": deps, "tree": tree}

    def test_case8_new_dependency_is_only_the_one_not_in_baseline(self):
        # 用例 8：对比项目依赖 {a, b}，本项目依赖 [a, c] → 新增依赖 ["c"]
        de = cl.diff_evidence(["a", "c"], [], [self.compared(["a", "b"], [])], None)
        self.assertEqual(de["new_dependencies"], ["c"])
        self.assertEqual(de["note"], "")
        self.assertEqual(de["compared_with"], [{"full_name": "own/b", "question_ids": ["RAG-F001"]}])

    def test_dependency_comparison_is_case_insensitive(self):
        de = cl.diff_evidence(["Requests"], [], [self.compared(["requests"], [])], None)
        self.assertEqual(de["new_dependencies"], [])

    def test_new_module_compares_normalised_first_level_dirs(self):
        tree = ["core/", "core/x.py", "docs/", "pkg_utils/"]
        base = ["core/", "pkgutils/"]
        de = cl.diff_evidence([], tree, [self.compared([], base)], None)
        self.assertEqual(de["new_modules_in_tree"], ["docs"])

    def test_incomplete_comparison_data_is_noted_and_lists_empty(self):
        de = cl.diff_evidence(["c"], ["docs/"], [self.compared(None, None)], None)
        self.assertEqual(de["new_dependencies"], [])
        self.assertEqual(de["new_modules_in_tree"], [])
        self.assertEqual(de["note"], "对比项目无缓存数据")

    def test_case5_no_comparison_projects_gives_direction_note(self):
        # 用例 C（协助决策 9.10 第 5 条）：没有同方向已出题项目 → 备注说明参考题库目录，列表仍为空
        de = cl.diff_evidence(["c"], ["docs/"], [], None)
        self.assertEqual(de["compared_with"], [])
        self.assertEqual(de["new_dependencies"], [])
        self.assertEqual(de["new_modules_in_tree"], [])
        self.assertEqual(de["note"],
                         "本方向尚无已出题项目可对比，请参考 题库目录.md 中同领域的题目判断差异")

    def test_release_change_is_passed_through(self):
        rc = {"from": "v1.0.0", "to": "v2.0.0"}
        de = cl.diff_evidence([], [], [], rc)
        self.assertEqual(de["release_change"], rc)


if __name__ == "__main__":
    unittest.main()


class DirectionDetailTest(unittest.TestCase):
    DIRS = {
        "rag": {"topics": ["rag"], "keywords": {"zh": ["检索增强"]}},
        "agent-framework": {"topics": ["ai-agents"], "keywords": {}},
        "fine-tuning": {"topics": ["lora"], "keywords": {}},
    }

    def test_lists_hits_sorted_by_score(self):
        text = cl.build_text("x/y", "检索增强 pipeline", ["rag", "lora"])
        detail = cl.direction_detail(self.DIRS, ["rag", "lora"], text)
        self.assertEqual([d["direction"] for d in detail], ["rag", "fine-tuning"])
        self.assertEqual(detail[0]["score"], 4)                  # topic rag ×3 + 关键词 检索增强 ×1
        self.assertEqual(detail[0]["topics"], ["rag"])
        self.assertEqual(detail[0]["keywords"], ["检索增强"])

    def test_detail_agrees_with_classify(self):
        text = cl.build_text("x/y", "agent tool", ["ai-agents"])
        top = cl.classify(self.DIRS, ["ai-agents"], "x/y", "agent tool")["direction"]
        self.assertEqual(cl.direction_detail(self.DIRS, ["ai-agents"], text)[0]["direction"], top)

    def test_format_when_nothing_hits(self):
        self.assertIn("unclassified", cl.format_detail([]))

