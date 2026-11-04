"""文档语言识别（方案 M4.1）。

只判断「文档语言」（仓库描述与 README）。编程语言 `language` 永远不参与判断。

规则：
1. 先按文字系统判断（不依赖模型）：假名占 CJK 字符 ≥ 5% → ja；韩文字母占字母 ≥ 20% → ko；
   汉字占字母 ≥ 20% 且无假名 → zh；西里尔字母占字母 ≥ 30% → 交给模型（区分 ru/uk 等）。
2. 拉丁字母文本交给模型：fast-langdetect；安装失败时退回 langdetect；两者都没有时返回 und + low。
3. 置信度：文字系统判断且字母样本 ≥ 200 → high；文字系统判断但样本 40–199 → medium（本实现的选择，
   方案未写明）；模型概率 ≥ 0.8 → high，0.5–0.8 → medium，否则 low；字母少于 40 → und + low。
4. 调用方负责把输入截成「描述 + README 清洗后前 3000 字」。

注意：假名判断要求假名至少 3 个，避免单个符号误判为日文（本实现的选择）。
"""
from __future__ import annotations

import re

MIN_LETTERS = 40          # 少于此字母数 → und + low
STRONG_LETTERS = 200      # 文字系统判断的高置信样本下限
KANA_RE = re.compile(r"[぀-ゟ゠-ヿ]")
HAN_RE = re.compile(r"[一-鿿㐀-䶿]")
HANGUL_RE = re.compile(r"[가-힯ᄀ-ᇿ㄰-㆏]")
CYR_RE = re.compile(r"[Ѐ-ӿ]")
GROUPS = {"en", "zh", "ja", "ko"}
_AUTO = object()          # 默认：加载已安装的模型


def _res(lang: str, conf: str, method: str) -> dict:
    return {"doc_lang": lang, "doc_lang_confidence": conf, "method": method}


def _conf_from_prob(p: float) -> str:
    if p >= 0.8:
        return "high"
    if p >= 0.5:
        return "medium"
    return "low"


def _normalize(code: str) -> str:
    code = (code or "").lower().replace("_", "-")
    if code.startswith("zh"):
        return "zh"
    return code.split("-")[0] or "und"


_default_model = None
_default_loaded = False


def load_default_model():
    """返回 (callable(text) -> (code, prob), 名称) 或 (None, None)。结果缓存。"""
    global _default_model, _default_loaded
    if _default_loaded:
        return _default_model
    _default_loaded = True
    try:
        from fast_langdetect import detect as fd_detect

        def run_fast(text: str):
            # 必须显式使用 model="lite"：只加载随包附带的 resources/lid.176.ftz，不联网。
            # 默认的 "auto" 与 "full" 会在运行时从境外地址下载完整模型，本项目禁止（协助决策 9.9）。
            r = fd_detect(text, model="lite", k=1)
            top = r[0]
            return str(top["lang"]), float(top["score"])
        run_fast("This is a probe sentence for the bundled model.")   # 加载失败时在此抛出，退回 langdetect
        _default_model = (run_fast, "fast-langdetect(lite)")
        return _default_model
    except Exception:
        pass
    try:
        from langdetect import DetectorFactory, detect_langs

        DetectorFactory.seed = 0      # langdetect 对短文本结果不稳定，固定随机种子使结果可重复

        def run_ld(text: str):
            top = detect_langs(text)[0]
            return str(top.lang), float(top.prob)
        run_ld("This is a probe sentence for the fallback model.")   # 加载失败时在此抛出
        _default_model = (run_ld, "langdetect")
        return _default_model
    except Exception:
        pass
    _default_model = None
    return None


def _model_step(text: str, model) -> dict:
    if model is _AUTO:
        loaded = load_default_model()
        model = loaded[0] if loaded else None
    if model is None:
        return _res("und", "low", "no-model")
    code, prob = model(text)
    return _res(_normalize(code), _conf_from_prob(prob), "model")


def detect(text: str, model=_AUTO) -> dict:
    """返回 {doc_lang, doc_lang_confidence, method}。

    model：默认 _AUTO（使用已安装的模型）；传 None 表示不用模型（测试用）；
    传 callable(text) -> (code, prob) 表示使用指定模型（测试用）。
    """
    t = text or ""
    letters = sum(1 for ch in t if ch.isalpha())
    if letters < MIN_LETTERS:
        return _res("und", "low", "too-short")
    kana = len(KANA_RE.findall(t))
    han = len(HAN_RE.findall(t))
    hangul = len(HANGUL_RE.findall(t))
    cyr = len(CYR_RE.findall(t))
    strong = letters >= STRONG_LETTERS
    if kana >= 3 and kana / (kana + han) >= 0.05:
        return _res("ja", "high" if strong else "medium", "script")
    if hangul / letters >= 0.20:
        return _res("ko", "high" if strong else "medium", "script")
    if han / letters >= 0.20:
        return _res("zh", "high" if strong else "medium", "script")
    # 西里尔字母 ≥ 30% 与其余拉丁文本一样交给模型
    return _model_step(t, model)


def lang_group(doc_lang: str) -> str:
    """语言组：en、zh、ja、ko；其余所有语言和 und 归入 other（方案 M4.1/M4.3）。"""
    return doc_lang if doc_lang in GROUPS else "other"
