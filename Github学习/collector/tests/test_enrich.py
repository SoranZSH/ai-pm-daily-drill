"""第 4 步：enrich.py 的单元测试（离线）。对应 M3 验收用例 10、11，并覆盖深采的整体结构。"""
import base64
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTOR = os.path.dirname(HERE)
sys.path.insert(0, COLLECTOR)

import enrich as en  # noqa: E402
import github_api as ga  # noqa: E402


def load_cfg():
    with open(os.path.join(COLLECTOR, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


README_FIXTURE = """# Demo Project

<!-- hidden comment that must go -->
<p align="center"><img src="logo.png"></p>

![logo](logo.png)
[![Build](https://img.shields.io/badge/build-passing-green)](https://ci.example)

Demo is a retrieval toolkit. See [the docs](https://docs.example).

```python
""" + "\n".join(f"print({i})" for i in range(30)) + """
```

## Installation

pip install demo

## Architecture

The core has three layers: index, retriever, and reranker.

## Features

- fast
- local

## License

MIT
"""


class ReadmeCleanTest(unittest.TestCase):
    """用例 10：徽章、图片、长代码块、安装段消失；Architecture 段排在最前；总长不超上限。"""

    def test_cleaning_rules(self):
        cfg = load_cfg()
        secs = en.clean_readme(README_FIXTURE, cfg["readme_max_chars"])
        headings = [s["heading"] for s in secs]
        self.assertEqual(headings[0], "Architecture")          # 优先段在最前
        self.assertIn("Features", headings)
        self.assertNotIn("Installation", headings)             # 安装段删除
        self.assertNotIn("License", headings)                  # 许可段删除
        joined = "\n".join(s["text"] for s in secs)
        self.assertNotIn("shields.io", joined)                 # 徽章行删除
        self.assertNotIn("![", joined)                         # 图片删除
        self.assertNotIn("<!--", joined)                       # HTML 注释删除
        self.assertNotIn("pip install", joined)
        self.assertIn("[代码块已省略]", joined)                  # 30 行代码块被省略
        self.assertIn("See the docs.", joined)                 # 链接保留为文字
        total = sum(len(s["text"]) for s in secs)
        self.assertLessEqual(total, cfg["readme_max_chars"])

    def test_length_cap_truncates_and_stops(self):
        secs = en.clean_readme(README_FIXTURE, 40)
        self.assertLessEqual(sum(len(s["text"]) for s in secs), 40)
        self.assertGreater(len(secs), 0)

    def test_hash_inside_code_block_is_not_a_heading(self):
        text = "# Title\n\n```bash\n# not a heading\necho hi\n```\n"
        secs = en.clean_readme(text, 1000)
        self.assertEqual([s["heading"] for s in secs], ["Title"])
        self.assertIn("# not a heading", secs[0]["text"])


class DependencyTest(unittest.TestCase):
    """用例 11：五种依赖文件的包名解析结果与期望一致。"""

    def test_pyproject(self):
        text = ('[project]\nname = "demo"\n'
                'dependencies = ["requests>=2.0", "click[extra]~=8.1", "numpy"]\n'
                '[tool.poetry.dependencies]\npython = "^3.11"\npydantic = "^2"\n')
        self.assertEqual(en.parse_dependencies("pyproject.toml", text),
                         ["requests", "click", "numpy", "pydantic"])

    def test_requirements(self):
        text = ("# comment\nrequests==2.31.0  # http\n-r base.txt\nflask>=2\n"
                'numpy ; python_version>"3"\n')
        self.assertEqual(en.parse_dependencies("requirements.txt", text),
                         ["requests", "flask", "numpy"])

    def test_package_json(self):
        text = json.dumps({"dependencies": {"react": "^18", "axios": "1"},
                           "devDependencies": {"jest": "29"}})
        self.assertEqual(en.parse_dependencies("package.json", text), ["react", "axios", "jest"])

    def test_go_mod(self):
        text = ("module example.com/app\n\ngo 1.22\n\nrequire (\n"
                "    github.com/spf13/cobra v1.8.0\n"
                "    golang.org/x/net v0.20.0 // indirect\n)\n\n"
                "require github.com/stretchr/testify v1.9.0\n")
        self.assertEqual(en.parse_dependencies("go.mod", text),
                         ["github.com/spf13/cobra", "golang.org/x/net",
                          "github.com/stretchr/testify"])

    def test_cargo(self):
        text = ('[package]\nname = "x"\n[dependencies]\nserde = "1"\n'
                'tokio = { version = "1", features = ["full"] }\n'
                '[dev-dependencies]\ncriterion = "0.5"\n')
        self.assertEqual(en.parse_dependencies("Cargo.toml", text), ["serde", "tokio"])

    def test_dedup_and_cap(self):
        text = "\n".join(f"pkg{i}" for i in range(80)) + "\npkg1\n"
        out = en.parse_dependencies("requirements.txt", text)
        self.assertEqual(len(out), en.MAX_DEP_NAMES)
        self.assertEqual(len(out), len(set(out)))


class TreeTest(unittest.TestCase):
    def test_top_two_levels_only_with_slash_for_dirs(self):
        items = [{"path": "README.md", "is_dir": False},
                 {"path": "src", "is_dir": True},
                 {"path": "src/main.py", "is_dir": False},
                 {"path": "src/core", "is_dir": True},
                 {"path": "src/core/engine.py", "is_dir": False}]
        self.assertEqual(en.tree_top2(items), ["README.md", "src/", "src/main.py", "src/core/"])


class EnrichProjectTest(unittest.TestCase):
    """完整深采流程（离线夹具）：结构、字段与其他语言 README、架构文档、release、语言占比、论文。"""

    def routes(self):
        return {
            "/repos/own/demo": {
                "full_name": "own/demo", "html_url": "https://github.com/own/demo",
                "description": "A demo", "topics": ["rag"], "language": "Python",
                "license": {"spdx_id": "MIT"}, "created_at": "2026-01-01T00:00:00Z",
                "pushed_at": "2026-10-09T00:00:00Z", "stargazers_count": 50,
                "default_branch": "main"},
            "/repos/own/demo/readme": {"content": b64(README_FIXTURE + "\nSee arXiv: https://arxiv.org/abs/2401.01234\n"),
                                       "encoding": "base64"},
            "/repos/own/demo/git/trees/main": {"truncated": False, "tree": [
                {"path": "README.md", "type": "blob"},
                {"path": "README.zh.md", "type": "blob"},
                {"path": "README.en.md", "type": "blob"},
                {"path": "ARCHITECTURE.md", "type": "blob"},
                {"path": "docs", "type": "tree"},
                {"path": "docs/design-notes.md", "type": "blob"},
                {"path": "src", "type": "tree"},
                {"path": "src/main.py", "type": "blob"},
                {"path": "src/core", "type": "tree"},
                {"path": "src/core/engine.py", "type": "blob"},
                {"path": "pyproject.toml", "type": "blob"},
                {"path": "CITATION.cff", "type": "blob"},
            ]},
            "/repos/own/demo/contents/ARCHITECTURE.md": {"content": b64("Arch: index then retrieve."), "encoding": "base64"},
            "/repos/own/demo/contents/docs/design-notes.md": {"content": b64("Design notes."), "encoding": "base64"},
            "/repos/own/demo/contents/README.en.md": {"content": b64("English readme."), "encoding": "base64"},
            "/repos/own/demo/contents/pyproject.toml": {"content": b64('[project]\ndependencies = ["requests>=2"]\n'), "encoding": "base64"},
            "/repos/own/demo/contents/CITATION.cff": {"content": b64('cff-version: 1.2.0\ntitle: "Demo: A Toolkit"\n'), "encoding": "base64"},
            "/repos/own/demo/releases": [
                {"draft": True, "tag_name": "v3.0.0-draft", "name": "x", "body": "", "published_at": None},
                {"draft": False, "tag_name": "v2.0.0", "name": "v2", "body": "notes", "published_at": "2026-09-01T00:00:00Z"},
            ],
            "/repos/own/demo/languages": {"Python": 900, "Shell": 100},
        }

    def test_full_enrich_shape(self):
        routes = self.routes()

        def handler(path, params):
            if path in routes:
                return ga.Response(200, {}, routes[path])
            return ga.Response(404, {}, None)

        api = ga.GitHubAPI(ga.FixtureTransport(handler=handler), "tok", sleep=lambda s: None)
        out = en.enrich_project(api, load_cfg(), "own/demo")

        self.assertEqual(out["meta"]["stars"], 50)
        self.assertEqual(out["meta"]["license"], "MIT")
        self.assertEqual(out["doc_langs_available"], ["zh", "en"])
        self.assertIsNotNone(out["readme_en_sections"])
        self.assertEqual(out["readme_en_sections"][0]["text"], "English readme.")
        self.assertEqual([a["path"] for a in out["arch_docs"]], ["ARCHITECTURE.md", "docs/design-notes.md"])
        self.assertEqual(out["tree_top2"], ["README.md", "README.zh.md", "README.en.md", "ARCHITECTURE.md",
                                            "docs/", "docs/design-notes.md", "src/", "src/main.py",
                                            "src/core/", "pyproject.toml", "CITATION.cff"])
        self.assertEqual(out["dependencies"], ["requests"])
        self.assertEqual(out["latest_release"]["tag"], "v2.0.0")       # 跳过 draft
        self.assertEqual(out["languages"], {"Python": 0.9, "Shell": 0.1})
        self.assertEqual(out["papers"][0]["title"], "Demo: A Toolkit")  # CITATION.cff 优先
        self.assertIn("arXiv:2401.01234", [p["title"] for p in out["papers"]])
        self.assertEqual(out["readme_sections"][0]["heading"], "Architecture")

    def test_repo_without_readme_or_tree(self):
        routes = {"/repos/own/bare": {"full_name": "own/bare", "default_branch": "main",
                                      "stargazers_count": 1}}

        def handler(path, params):
            return ga.Response(200, {}, routes[path]) if path in routes else ga.Response(404, {}, None)

        api = ga.GitHubAPI(ga.FixtureTransport(handler=handler), "tok", sleep=lambda s: None)
        out = en.enrich_project(api, load_cfg(), "own/bare")
        self.assertEqual(out["readme_sections"], [])
        self.assertIsNone(out["readme_en_sections"])
        self.assertEqual(out["tree_top2"], [])
        self.assertEqual(out["dependencies"], [])
        self.assertIsNone(out["latest_release"])
        self.assertEqual(out["languages"], {})

    def test_meta_failure_raises_request_failed(self):
        def handler(path, params):
            return ga.Response(404, {}, None)     # 元数据 404 → 视为请求失败，由调用方跳过项目

        api = ga.GitHubAPI(ga.FixtureTransport(handler=handler), "tok", sleep=lambda s: None)
        with self.assertRaises(ga.RequestFailed):
            en.enrich_project(api, load_cfg(), "own/gone")


if __name__ == "__main__":
    unittest.main()
