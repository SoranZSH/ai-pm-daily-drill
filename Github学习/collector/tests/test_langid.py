"""第 1 步（M4.1）：langid.py 的单元测试（离线）。对应 M4 验收用例 1、2 中的文字系统部分。

模型部分用 stub（model=lambda text: (code, prob)）代替 fast-langdetect，不依赖网络或安装。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import langid  # noqa: E402

ZH = "检索增强生成（RAG）是一种把外部知识库与大语言模型结合的方法。本项目提供中文文档、示例和评测脚本，适合初学者快速搭建知识库问答系统。"
JA = "この リポジトリは検索拡張生成のためのツールです。ナレッジベースと連携して質問に答えます。ドキュメントは日本語で書かれています。"
KO = "이 저장소는 검색 증강 생성을 위한 도구입니다. 지식 베이스와 연결하여 질문에 답합니다. 문서는 한국어로 작성되어 있습니다."
RU = "Этот репозиторий содержит инструменты для поиска по базе знаний и генерации ответов. Документация написана на русском языке."
ES = "Este repositorio ofrece herramientas para construir asistentes con base de conocimiento y generación aumentada de respuestas."
EN = "This repository provides a complete English guide to retrieval augmented generation, with examples and benchmarks."
MIXED_ZH = "这是一个用于检索增强生成的开源框架，支持知识库与向量检索，适合中文开发者。 It also ships an English quick start."


def no_model(text):
    raise AssertionError("不应调用模型")


class ScriptRuleTest(unittest.TestCase):
    """文字系统判断：不依赖模型（model=None 时仍然可用）。"""

    def test_chinese_is_zh_without_model(self):
        r = langid.detect(ZH, model=None)
        self.assertEqual((r["doc_lang"], r["method"]), ("zh", "script"))
        self.assertEqual(r["doc_lang_confidence"], "medium")       # 样本 40–199 字

    def test_long_chinese_is_high(self):
        r = langid.detect(ZH * 4, model=None)                      # 字母数 ≥ 200
        self.assertEqual((r["doc_lang"], r["doc_lang_confidence"]), ("zh", "high"))

    def test_japanese_has_kana(self):
        r = langid.detect(JA, model=None)
        self.assertEqual(r["doc_lang"], "ja")

    def test_korean_hangul(self):
        r = langid.detect(KO, model=None)
        self.assertEqual(r["doc_lang"], "ko")

    def test_mixed_chinese_majority_is_zh(self):
        self.assertEqual(langid.detect(MIXED_ZH, model=None)["doc_lang"], "zh")

    def test_twenty_characters_is_und_low(self):
        r = langid.detect("这是一个只有二十个字的中文描述文本啊啊啊啊啊", model=None)
        self.assertEqual((r["doc_lang"], r["doc_lang_confidence"], r["method"]), ("und", "low", "too-short"))

    def test_empty_and_none_are_und(self):
        self.assertEqual(langid.detect("", model=None)["doc_lang"], "und")
        self.assertEqual(langid.detect(None, model=None)["doc_lang"], "und")

    def test_script_rules_never_call_model(self):
        self.assertEqual(langid.detect(ZH, model=no_model)["doc_lang"], "zh")
        self.assertEqual(langid.detect(KO, model=no_model)["doc_lang"], "ko")


class ModelStepTest(unittest.TestCase):
    """拉丁与西里尔文本交给模型；模型不可用时返回 und + low。"""

    def test_no_model_gives_und_low(self):
        r = langid.detect(RU, model=None)
        self.assertEqual((r["doc_lang"], r["doc_lang_confidence"], r["method"]), ("und", "low", "no-model"))
        r = langid.detect(ES, model=None)
        self.assertEqual(r["doc_lang"], "und")

    def test_cyrillic_uses_model(self):
        r = langid.detect(RU, model=lambda t: ("ru", 0.9))
        self.assertEqual((r["doc_lang"], r["doc_lang_confidence"]), ("ru", "high"))

    def test_probability_thresholds(self):
        self.assertEqual(langid.detect(ES, model=lambda t: ("es", 0.6))["doc_lang_confidence"], "medium")
        self.assertEqual(langid.detect(ES, model=lambda t: ("es", 0.3))["doc_lang_confidence"], "low")
        self.assertEqual(langid.detect(ES, model=lambda t: ("es", 0.8))["doc_lang_confidence"], "high")

    def test_model_code_normalised(self):
        self.assertEqual(langid.detect(EN, model=lambda t: ("zh-cn", 0.95))["doc_lang"], "zh")
        self.assertEqual(langid.detect(EN, model=lambda t: ("en", 0.95))["doc_lang"], "en")

    def test_english_text_goes_to_model(self):
        r = langid.detect(EN, model=lambda t: ("en", 0.99))
        self.assertEqual((r["doc_lang"], r["method"]), ("en", "model"))


def _model_available():
    return langid.load_default_model() is not None


@unittest.skipUnless(_model_available(), "未安装 fast-langdetect 或 langdetect")
class RealModelTest(unittest.TestCase):
    """验收用例 1：真实模型识别西班牙语、俄语、英语。默认只用随包附带的 lite 模型，不联网。"""

    def test_es_ru_en(self):
        self.assertEqual(langid.detect(ES)["doc_lang"], "es")
        self.assertEqual(langid.detect(RU)["doc_lang"], "ru")
        r = langid.detect(EN)
        self.assertEqual((r["doc_lang"], r["method"]), ("en", "model"))

    def test_bundled_lite_model_or_langdetect_fallback(self):
        self.assertIn(langid.load_default_model()[1], ("fast-langdetect(lite)", "langdetect"))


class GroupTest(unittest.TestCase):
    def test_groups(self):
        self.assertEqual([langid.lang_group(x) for x in ("en", "zh", "ja", "ko")], ["en", "zh", "ja", "ko"])
        self.assertEqual([langid.lang_group(x) for x in ("es", "ru", "und")], ["other", "other", "other"])


if __name__ == "__main__":
    unittest.main()
