"""HTTP 封装（方案 M3.6）。

- Token、代理、超时、限额、重试都集中在这里。
- 真实传输层 RealTransport 使用 requests（只在真正联网时才导入）；
  测试使用 FixtureTransport 或注入的 handler，完全不触网。
- Token 只放在请求头里；任何异常信息和日志都经过 redact() 脱敏。
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass

API_BASE = "https://api.github.com"
API_VERSION = "2026-03-10"
USER_AGENT = "github-learning-collector"

RETRY_GAPS = (2, 5)          # 5xx 与网络错误最多重试 2 次，间隔 2 秒、5 秒
MAX_RATE_WAIT = 600          # 限额等待超过 10 分钟 → 结束本次运行
MAX_RATE_ATTEMPTS = 4        # 限额等待的最多次数，防止死循环
CONSECUTIVE_FAIL_LIMIT = 3   # 连续 3 次请求失败（重试耗尽后）→ 中断


class TransportError(Exception):
    """网络层错误：超时、连接失败等。"""


class ConfigError(Exception):
    """配置错误，例如未安装 requests。"""


class FixtureMissing(Exception):
    """测试夹具缺失。属于配置/测试错误，不重试，直接报错。"""


class RequestFailed(Exception):
    """某个请求失败（非网络原因，例如返回了意外的状态码）。调用方可以跳过当前项目。"""


class NetworkRequestFailed(RequestFailed):
    """网络错误、连接失败或 5xx 在重试耗尽后仍失败。

    协助决策 9.10 第 4 条：搜索、已出题仓库解析等阶段遇到此错误 → 本次运行中断，退出码 3，记 partial，水位线不动。
    """


class FatalNetwork(Exception):
    """连续多次请求失败：中途网络错误，本次运行中断（退出码 3）。"""


class BudgetExhausted(Exception):
    """限额等待超过上限：本次运行结束（记 partial）。"""


@dataclass
class Response:
    status: int
    headers: dict
    body: object = None


def redact(text: str, token: str | None) -> str:
    """把 Token（及其 Bearer 形式）从任意文本中去掉。"""
    if not text:
        return text
    if token:
        text = text.replace(token, "***")
    return re.sub(r"(?i)bearer\s+[A-Za-z0-9_\-\.]+", "Bearer ***", text)


def fixture_name(path: str, params: dict | None = None) -> str:
    """夹具文件名映射规则，见 tests/fixtures/README.md。"""
    key = path.strip("/")
    if params:
        key += "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
    return re.sub(r"[^A-Za-z0-9._=-]", "_", key) + ".json"


class RealTransport:
    """真实网络。requests 只在这里导入。"""

    def __init__(self, proxy: str = ""):
        try:
            import requests  # noqa: WPS433 (延迟导入：测试与未联网时不需要)
        except ImportError as e:
            raise ConfigError("未安装 requests，请先执行：python -m pip install requests") from e
        self._requests = requests
        self._session = requests.Session()
        if proxy:
            self._session.proxies = {"http": proxy, "https": proxy}

    def get(self, path, params=None, headers=None, timeout=15) -> Response:
        try:
            r = self._session.get(API_BASE + path, params=params, headers=headers, timeout=timeout)
        except self._requests.RequestException as e:
            # 只保留异常类型名，避免把请求细节（含可能的凭据）写进错误信息
            raise TransportError(type(e).__name__) from None
        body = None
        if r.content:
            try:
                body = r.json()
            except ValueError:
                body = None
        return Response(r.status_code, {k.lower(): v for k, v in r.headers.items()}, body)


class FixtureTransport:
    """离线夹具。按 fixture_name() 的规则读取 JSON；或使用 handler 函数。"""

    def __init__(self, fixtures_dir: str | None = None, handler=None):
        self.dir = fixtures_dir
        self.handler = handler
        self.calls: list[tuple[str, dict]] = []   # 用于验收：统计网络请求次数

    def get(self, path, params=None, headers=None, timeout=15) -> Response:
        params = dict(params or {})
        self.calls.append((path, params))
        if self.handler is not None:
            return self.handler(path, params)
        name = fixture_name(path, params)
        fp = os.path.join(self.dir or "", name)
        if not os.path.isfile(fp):
            raise FixtureMissing(f"找不到夹具：{name}")
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
        headers_lower = {k.lower(): v for k, v in (d.get("headers") or {}).items()}
        return Response(int(d.get("status", 200)), headers_lower, d.get("body"))


PROXY_TOKEN = "__proxy__"


class GitHubAPI:
    """带重试、限额与中断规则的 API 客户端。所有时间相关函数都可注入，便于测试。"""

    def __init__(self, transport, token: str, *, sleep=time.sleep, now=time.time,
                 mono=time.monotonic, search_interval: float = 2.1, log=None):
        self.t = transport
        self.token = token
        self.sleep = sleep
        self.now = now              # 墙钟（用于 x-ratelimit-reset）
        self.mono = mono            # 单调时钟（用于搜索间隔）
        self.search_interval = search_interval
        self.log = log or (lambda level, msg: None)
        self.calls = 0              # 每次发出的请求（含重试）都计数
        self.consecutive_failures = 0
        self._last_search: float | None = None

    # ---- 内部 ----
    def _headers(self) -> dict:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        }
        # 特殊值 PROXY_TOKEN：凭据由外部代理注入（云端初始化运行用），本程序不发送 Authorization
        if self.token and self.token != PROXY_TOKEN:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _log(self, level: str, msg: str) -> None:
        self.log(level, redact(msg, self.token))

    def _rate_wait(self, r: Response) -> float | None:
        h = r.headers
        if "retry-after" in h:
            try:
                return float(h["retry-after"])
            except ValueError:
                return None
        if h.get("x-ratelimit-remaining") == "0" and "x-ratelimit-reset" in h:
            try:
                return max(0.0, float(h["x-ratelimit-reset"]) - self.now())
            except ValueError:
                return None
        return None

    def _failed(self, path: str, why: str) -> None:
        self.consecutive_failures += 1
        self._log("WARNING", f"请求失败：{path}（{why}）")
        if self.consecutive_failures >= CONSECUTIVE_FAIL_LIMIT:
            raise FatalNetwork(f"连续 {self.consecutive_failures} 次请求失败")
        raise NetworkRequestFailed(f"{path}：{why}")

    # ---- 对外 ----
    def preflight(self, timeout: float = 5.0):
        """GET /rate_limit，不重试。网络失败抛 TransportError；返回 JSON。"""
        self.calls += 1
        r = self.t.get("/rate_limit", headers=self._headers(), timeout=timeout)
        if r.status != 200:
            raise TransportError(f"rate_limit 返回 {r.status}")
        return r.body

    def get(self, path: str, params: dict | None = None, *, timeout: float = 15.0) -> Response:
        """GET 一个接口：处理 403/429 限额、5xx 与网络错误重试。

        返回最终 Response（包括 404 等业务状态，由调用方判断）。
        """
        retries = 0
        rate_attempts = 0
        while True:
            self.calls += 1
            try:
                r = self.t.get(path, params=params, headers=self._headers(), timeout=timeout)
            except TransportError as e:
                if retries < len(RETRY_GAPS):
                    self.sleep(RETRY_GAPS[retries])
                    retries += 1
                    continue
                self._failed(path, f"网络错误：{e}")

            if r.status in (403, 429):
                wait = self._rate_wait(r)
                if wait is not None:
                    rate_attempts += 1
                    if wait > MAX_RATE_WAIT or rate_attempts > MAX_RATE_ATTEMPTS:
                        raise BudgetExhausted(f"限额需等待约 {int(wait)} 秒，超过上限")
                    self._log("INFO", f"触发限额，等待 {int(wait)} 秒后重试：{path}")
                    self.sleep(wait)
                    continue

            if 500 <= r.status < 600:
                if retries < len(RETRY_GAPS):
                    self.sleep(RETRY_GAPS[retries])
                    retries += 1
                    continue
                self._failed(path, f"服务器错误 {r.status}")

            self.consecutive_failures = 0
            return r

    def search_repos(self, q: str, page: int = 1, per_page: int = 100) -> Response:
        """搜索接口：两次调用间隔 ≥ search_interval 秒（方案 M3.6）。"""
        if self._last_search is not None:
            gap = self.mono() - self._last_search
            if gap < self.search_interval:
                self.sleep(self.search_interval - gap)
        self._last_search = self.mono()
        return self.get("/search/repositories", {
            "q": q, "sort": "stars", "order": "desc",
            "per_page": per_page, "page": page,
        })
