# 测试夹具说明

## 映射规则（`github_api.FixtureTransport`）

单元测试通过夹具目录代替真实网络。请求按「路径 + 排序后的查询参数」映射到文件：

1. `key = 路径去掉首尾 "/"`；若有查询参数，追加 `?` + `k1=v1&k2=v2`（按键名排序）。
2. 文件名 = `key` 中所有不属于 `A-Z a-z 0-9 . _ = -` 的字符替换为 `_`，再加 `.json`。

示例：`GET /repos/psf/requests/stargazers/history?per_page=2`
→ `repos_psf_requests_stargazers_history_per_page=2.json`

找不到对应文件时直接报错（`FixtureMissing`），不会静默返回空数据。

## 文件格式

```json
{"status": 200, "headers": {"link": "..."}, "body": <JSON 内容>}
```

- `status` 缺省为 200；`headers` 键名统一小写；`body` 即响应 JSON。
- 对于需要模拟网络失败的场景，测试代码直接注入异常，不使用夹具文件。

## 文件清单

| 文件 | 来源 |
|---|---|
| `stargazers_history_real_psf_requests.json` | 真实接口返回（`psf/requests`，`per_page=2`），方案 v1.1 第 9.6 节记录，2026-10-10 由用户实测 |
| `repos_psf_requests_stargazers_history_per_page=2.json` | 同上，按映射规则命名、带 `status`/`headers`/`body` 包装的版本 |
