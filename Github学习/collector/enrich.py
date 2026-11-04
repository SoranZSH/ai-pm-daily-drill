"""深采（方案 M3.9）：对入选项目取元数据、README、目录树、架构文档、依赖、release、语言占比、论文。

约定（M3 阶段）：
- 本模块不做语言识别；英文版 README 只要仓库里存在就抓取（readme_en_sections），
  是否需要保留由 M4 的文档语言识别决定。
- 失败处理：单个请求重试耗尽 → 抛 ga.RequestFailed（调用方跳过该项目）；
  连续多次失败 → ga.FatalNetwork（调用方中断本次运行，退出码 3）。
"""
from __future__ import annotations

import base64
import json
import re
import tomllib
from urllib.parse import quote

import github_api as ga

PRIORITY_WORDS = [
    "feature", "architecture", "how it works", "design", "why", "overview", "concept",
    "principle", "特性", "功能", "架构", "原理", "设计", "为什么", "简介", "概述",
    "特徴", "機能", "アーキテクチャ", "仕組み", "概要", "특징", "기능", "아키텍처", "구조",
    "архитектура", "возможности",
]
EXCLUDE_WORDS = [
    "install", "installation", "license", "contributing", "contributors", "star history",
    "sponsor", "安装", "许可", "贡献", "インストール", "ライセンス", "설치",
]
CODE_LINE_LIMIT = 15
MAX_DEP_NAMES = 60
README_LANG_RE = re.compile(r"^README[._-]?([A-Za-z]{2})(?:[-_][A-Za-z]{2})?\.md$", re.IGNORECASE)
ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})")


# ---------------- README 清洗 ----------------

def clean_readme(text: str, max_chars: int) -> list[dict]:
    """README 清洗（M3.9 的 9 条规则）。返回 [{heading, text}]。

    解释：代码块内部不做 HTML/图片/链接处理，只做长度省略（规则 3）；
    标题切分时同样跳过代码块内的 '#' 行。
    """
    if not text:
        return []
    # 切分代码块与非代码段（规则 3 的前置）
    segments: list[tuple[bool, list[str]]] = []   # (is_code, lines)
    in_code = False
    buf: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.strip().startswith("```"):
            if in_code:
                buf.append(line)
                segments.append((True, buf))
                buf = []
                in_code = False
            else:
                if buf:
                    segments.append((False, buf))
                buf = [line]
                in_code = True
            continue
        buf.append(line)
    if buf:
        segments.append((in_code, buf))

    out_lines: list[str] = []
    for is_code, lines in segments:
        if is_code:
            body = lines[1:-1] if len(lines) >= 2 and lines[-1].strip().startswith("```") else lines[1:]
            if len(body) > CODE_LINE_LIMIT:                                  # 规则 3
                out_lines.append("[代码块已省略]")
            else:
                out_lines.extend(lines)
            continue
        chunk = "\n".join(lines)
        chunk = re.sub(r"<!--.*?-->", "", chunk, flags=re.DOTALL)           # 规则 1
        chunk = re.sub(r"</?[A-Za-z][^>\n]*>", "", chunk)                    # 规则 1
        chunk = re.sub(r"!\[[^\]\n]*\]\([^)\n]*\)", "", chunk)               # 规则 2
        kept = [ln for ln in chunk.split("\n")
                if "shields.io" not in ln.lower() and "badge" not in ln.lower()]  # 规则 2
        chunk = "\n".join(kept)
        chunk = re.sub(r"\[([^\]\n]*)\]\([^)\n]*\)", r"\1", chunk)           # 规则 4
        out_lines.extend(chunk.split("\n"))

    joined = "\n".join(out_lines)
    joined = re.sub(r"\n{3,}", "\n\n", joined)                              # 规则 5

    # 规则 6：按标题（#～###）切段，代码块内的 '#' 不算标题
    sections: list[dict] = []
    cur = {"heading": "简介", "lines": []}
    in_code = False
    for line in joined.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
        m = None if in_code else re.match(r"^#{1,3}\s+(.*\S)\s*$", line)
        if m:
            sections.append(cur)
            cur = {"heading": m.group(1).strip(), "lines": []}
        else:
            cur["lines"].append(line)
    sections.append(cur)
    sections = [{"heading": s["heading"], "text": "\n".join(s["lines"]).strip()}
                for s in sections]
    sections = [s for s in sections if s["text"] or s["heading"] != "简介"]

    # 规则 9：删除安装、许可等段（先删，避免占用长度预算）
    sections = [s for s in sections
                if not any(w in s["heading"].lower() for w in EXCLUDE_WORDS)]

    # 规则 7：优先段排在前面（稳定排序）
    def is_priority(s):
        h = s["heading"].lower()
        return any(w in h for w in PRIORITY_WORDS)
    sections = sorted(sections, key=lambda s: 0 if is_priority(s) else 1)

    # 规则 8：按总长度截断
    result: list[dict] = []
    total = 0
    for s in sections:
        if not s["text"]:
            continue
        room = max_chars - total
        if room <= 0:
            break
        if len(s["text"]) > room:
            result.append({"heading": s["heading"], "text": s["text"][:room]})
            break
        result.append(s)
        total += len(s["text"])
    return result


# ---------------- 依赖解析 ----------------

def _pkg_name(spec: str) -> str:
    return re.split(r"[<>=!~;\[ ]", spec.strip(), maxsplit=1)[0].strip()


def parse_dependencies(filename: str, text: str) -> list[str]:
    names: list[str] = []
    try:
        if filename == "pyproject.toml":
            d = tomllib.loads(text)
            for spec in (d.get("project", {}).get("dependencies") or []):
                names.append(_pkg_name(spec))
            poetry = d.get("tool", {}).get("poetry", {}).get("dependencies") or {}
            names.extend(k for k in poetry if k.lower() != "python")
        elif filename == "requirements.txt":
            for line in text.splitlines():
                line = line.split("#", 1)[0].strip()
                if not line or line.startswith("-"):
                    continue
                names.append(_pkg_name(line))
        elif filename == "package.json":
            d = json.loads(text)
            names.extend((d.get("dependencies") or {}).keys())
            names.extend((d.get("devDependencies") or {}).keys())
        elif filename == "go.mod":
            in_block = False
            for raw in text.splitlines():
                line = raw.split("//", 1)[0].strip()
                if line.startswith("require ("):
                    in_block = True
                    continue
                if in_block:
                    if line == ")":
                        in_block = False
                    elif line:
                        names.append(line.split()[0])
                elif line.startswith("require "):
                    parts = line.split()
                    if len(parts) >= 2:
                        names.append(parts[1])
        elif filename == "Cargo.toml":
            d = tomllib.loads(text)
            names.extend((d.get("dependencies") or {}).keys())
    except (ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError):
        return []
    out: list[str] = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out[:MAX_DEP_NAMES]


# ---------------- 目录树 ----------------

def tree_top2(items: list[dict]) -> list[str]:
    """items: [{path, is_dir}]。取前两层路径，目录以 / 结尾，最多 200 条。"""
    out: list[str] = []
    for it in items:
        depth = it["path"].count("/") + 1
        if depth > 2:
            continue
        out.append(it["path"] + ("/" if it["is_dir"] else ""))
        if len(out) >= 200:
            break
    return out


# ---------------- 深采 ----------------

def _decode(content_b64: str) -> str:
    return base64.b64decode(content_b64.replace("\n", "")).decode("utf-8", errors="replace")


def _get(api: ga.GitHubAPI, path: str, params: dict | None = None, *, ok_404: bool = False):
    r = api.get(path, params)
    if r.status == 200:
        return r.body
    if r.status == 404 and ok_404:
        return None
    raise ga.RequestFailed(f"{path}：HTTP {r.status}")


def _file_text(api: ga.GitHubAPI, full: str, path: str) -> str | None:
    body = _get(api, f"/repos/{full}/contents/{quote(path)}", ok_404=True)
    if isinstance(body, dict) and body.get("content"):
        return _decode(body["content"])
    return None


def fetch_latest_release(api: ga.GitHubAPI, full_name: str, max_chars: int) -> dict | None:
    """最新 release（第一条非草稿）；没有时返回 None。初筛（复收判断）与深采共用。"""
    rels = _get(api, f"/repos/{full_name}/releases", {"per_page": 2}, ok_404=True) or []
    for rel in rels:
        if not rel.get("draft"):
            return {
                "tag": rel.get("tag_name"),
                "name": rel.get("name"),
                "text": (rel.get("body") or "")[:max_chars],
                "published_at": rel.get("published_at"),
            }
    return None


def fetch_readme_raw(api: ga.GitHubAPI, full_name: str) -> str:
    """README 原文；仓库没有 README 时返回空字符串。初筛（语言识别）与深采共用（协助决策 9.9）。"""
    body = _get(api, f"/repos/{full_name}/readme", ok_404=True)
    if isinstance(body, dict) and body.get("content"):
        return _decode(body["content"])
    return ""


def enrich_project(api: ga.GitHubAPI, cfg: dict, full_name: str, readme_raw: str | None = None) -> dict:
    """返回深采结果（字段见方案 2.6 节，M3 阶段未实现的字段为占位值）。

    readme_raw：初筛阶段已取得的 README 原文；传入时不再请求 /readme。
    """
    base = f"/repos/{full_name}"
    meta = _get(api, base)
    branch = meta.get("default_branch") or "main"

    # README（不存在时为空字符串）
    if readme_raw is None:
        readme_raw = fetch_readme_raw(api, full_name)

    # 目录树：truncated 时退化为仅第一层
    tree_body = _get(api, f"{base}/git/trees/{quote(branch)}", {"recursive": 1}, ok_404=True) or {}
    if tree_body.get("truncated"):
        listing = _get(api, f"{base}/contents/", ok_404=True) or []
        items = [{"path": e["name"], "is_dir": e.get("type") == "dir"} for e in listing]
    else:
        items = [{"path": e["path"], "is_dir": e.get("type") == "tree"}
                 for e in (tree_body.get("tree") or [])]

    root_files = {it["path"]: it for it in items if "/" not in it["path"] and not it["is_dir"]}

    # 其他语言 README：只记录语言代码；英文版抓取并清洗
    langs_available: list[str] = []
    en_name = None
    for name in root_files:
        m = README_LANG_RE.match(name)
        if m:
            code = m.group(1).lower()
            if code not in langs_available:
                langs_available.append(code)
            if code == "en":
                en_name = name
    readme_en_sections = None
    if en_name:
        en_text = _file_text(api, full_name, en_name)
        readme_en_sections = clean_readme(en_text or "", cfg["readme_max_chars"])

    # 架构文档：根目录 ARCHITECTURE.md / DESIGN.md，或 docs/ 下名称含 architecture/design 的 .md，最多 2 个
    arch_paths: list[str] = []
    for it in items:
        p = it["path"]
        if not it["is_dir"] and "/" not in p and p.upper() in ("ARCHITECTURE.MD", "DESIGN.MD"):
            arch_paths.append(p)
        elif (not it["is_dir"] and p.startswith("docs/") and p.lower().endswith(".md")
              and ("architecture" in p.lower() or "design" in p.lower())):
            arch_paths.append(p)
    arch_docs = []
    for p in arch_paths[:2]:
        text = _file_text(api, full_name, p)
        if text is not None:
            arch_docs.append({"path": p, "text": text[: cfg["arch_doc_max_chars"]]})

    # 依赖文件
    dependencies: list[str] = []
    for fname in ("pyproject.toml", "requirements.txt", "package.json", "go.mod", "Cargo.toml"):
        if fname in root_files:
            text = _file_text(api, full_name, fname)
            if text:
                for n in parse_dependencies(fname, text):
                    if n not in dependencies and len(dependencies) < MAX_DEP_NAMES:
                        dependencies.append(n)

    # 最新 release（第一条非草稿）
    latest_release = fetch_latest_release(api, full_name, cfg["release_max_chars"])

    # 语言占比（两位小数的比例）
    raw_langs = _get(api, f"{base}/languages", ok_404=True) or {}
    total_bytes = sum(raw_langs.values()) or 0
    languages = {k: round(v / total_bytes, 2) for k, v in raw_langs.items()} if total_bytes else {}

    # 论文：README 中的 arXiv 链接；CITATION.cff 的 title
    citation_title = None
    if "CITATION.cff" in root_files:
        cff = _file_text(api, full_name, "CITATION.cff") or ""
        m = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", cff, re.MULTILINE)
        if m:
            citation_title = m.group(1)
    papers = []
    seen = set()
    for pid in ARXIV_RE.findall(readme_raw):
        if pid not in seen:
            seen.add(pid)
            papers.append({"title": f"arXiv:{pid}", "url": f"https://arxiv.org/abs/{pid}"})
    if citation_title:
        papers.insert(0, {"title": citation_title, "url": meta.get("html_url") or ""})

    return {
        "meta": {
            "full_name": meta.get("full_name") or full_name,
            "html_url": meta.get("html_url"),
            "description": meta.get("description"),
            "topics": meta.get("topics") or [],
            "language": meta.get("language"),
            "license": (meta.get("license") or {}).get("spdx_id"),
            "created_at": meta.get("created_at"),
            "pushed_at": meta.get("pushed_at"),
            "stars": int(meta.get("stargazers_count") or 0),
            "default_branch": branch,
        },
        "readme_sections": clean_readme(readme_raw, cfg["readme_max_chars"]),
        "readme_en_sections": readme_en_sections,
        "doc_langs_available": langs_available,
        "tree_top2": tree_top2(items),
        "arch_docs": arch_docs,
        "dependencies": dependencies,
        "latest_release": latest_release,
        "languages": languages,
        "papers": papers,
    }
