"""SQLite 存储（方案 M3.4）。表结构与字段按方案执行，建表使用 CREATE TABLE IF NOT EXISTS。

注意：本模块只读写 state.db，不读取题库，也不读取每日一题的学习记录。
"""
from __future__ import annotations

import json
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    started_at   TEXT,
    finished_at  TEXT,
    status       TEXT,
    window_start TEXT,
    window_end   TEXT,
    pack_file    TEXT,
    api_calls    INTEGER,
    note         TEXT
);
CREATE TABLE IF NOT EXISTS repos (
    repo_id           INTEGER PRIMARY KEY,
    full_name         TEXT,
    html_url          TEXT,
    first_seen_at     TEXT,
    last_seen_at      TEXT,
    status            TEXT,
    status_reason     TEXT,
    direction         TEXT,
    doc_lang          TEXT,
    packed_in         TEXT,
    packed_at         TEXT,
    questioned_at     TEXT,
    last_release_tag  TEXT,
    gain_at_first_pack INTEGER
);
CREATE TABLE IF NOT EXISTS candidate_gains (
    run_id      TEXT,
    repo_id     INTEGER,
    lang_group  TEXT,
    gain        INTEGER,
    days        INTEGER,
    recorded_at TEXT,
    PRIMARY KEY (run_id, repo_id)
);
CREATE TABLE IF NOT EXISTS enrich_cache (
    repo_id    INTEGER PRIMARY KEY,
    run_id     TEXT,
    fetched_at TEXT,
    payload    TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id     INTEGER NOT NULL,
    stars       INTEGER NOT NULL,
    taken_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_repo ON snapshots(repo_id, snapshot_id);
"""


def connect(path: str) -> sqlite3.Connection:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # M4 迁移：M3 建的 candidate_gains 没有 recorded_at，补上（CREATE TABLE IF NOT EXISTS 不会改已有表）
    cols = {r[1] for r in conn.execute("PRAGMA table_info(candidate_gains)")}
    if "recorded_at" not in cols:
        conn.execute("ALTER TABLE candidate_gains ADD COLUMN recorded_at TEXT")
        conn.commit()
    # M5 迁移（协助决策 9.10 第 2 条）：gain_at_first_pack 改为「日均新增」。
    # 旧值是整个窗口的总增量，无法换算为日均，因此清空，由「第一次再被观察到」的数值补上。
    if conn.execute("SELECT 1 FROM meta WHERE key = 'gain_unit'").fetchone() is None:
        conn.execute("UPDATE repos SET gain_at_first_pack = NULL")
        conn.execute("INSERT INTO meta(key, value) VALUES('gain_unit', 'daily')")
        conn.commit()
    return conn


class Store:
    def __init__(self, path: str):
        self.path = path
        self.conn = connect(path)

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    # ---- meta ----
    def meta_get(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def meta_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def meta_get_json(self, key: str, default=None):
        raw = self.meta_get(key)
        return json.loads(raw) if raw else default

    def meta_set_json(self, key: str, value) -> None:
        self.meta_set(key, json.dumps(value, ensure_ascii=False))

    def last_success_until(self) -> str | None:
        return self.meta_get("last_success_until")

    # ---- runs ----
    def run_exists(self, run_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone() is not None

    def add_run(self, **f) -> None:
        cols = ["run_id", "started_at", "finished_at", "status", "window_start",
                "window_end", "pack_file", "api_calls", "note"]
        vals = [f.get(c) for c in cols]
        self.conn.execute(
            f"INSERT INTO runs({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)

    # ---- repos ----
    def get_repo(self, repo_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM repos WHERE repo_id = ?", (repo_id,)).fetchone()
        return dict(row) if row else None

    def repo_by_full_name(self, full_name: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM repos WHERE lower(full_name) = lower(?)", (full_name,)).fetchone()
        return dict(row) if row else None

    def upsert_repo(self, repo_id: int, full_name: str, html_url: str, now_iso: str) -> None:
        self.conn.execute(
            "INSERT INTO repos(repo_id, full_name, html_url, first_seen_at, last_seen_at, status) "
            "VALUES(?, ?, ?, ?, ?, 'seen') "
            "ON CONFLICT(repo_id) DO UPDATE SET full_name = excluded.full_name, "
            "html_url = excluded.html_url, last_seen_at = excluded.last_seen_at",
            (repo_id, full_name, html_url, now_iso, now_iso))

    def set_repo_status(self, repo_id: int, status: str, reason: str | None = None,
                        questioned_at: str | None = None) -> None:
        self.conn.execute(
            "UPDATE repos SET status = ?, status_reason = ?, "
            "questioned_at = COALESCE(?, questioned_at) WHERE repo_id = ?",
            (status, reason, questioned_at, repo_id))

    def mark_packed(self, repo_id: int, run_id: str, now_iso: str, daily_gain: float,
                    release_tag: str | None) -> None:
        # gain_at_first_pack 字段语义：首次记录时的「日均新增」（gain ÷ 窗口天数），只在为空时写入。
        # last_release_tag 无 release 时记空字符串，表示「已查过，没有 release」，避免重复请求
        self.conn.execute(
            "UPDATE repos SET status = 'packed', packed_in = ?, packed_at = ?, "
            "gain_at_first_pack = COALESCE(gain_at_first_pack, ?), "
            "last_release_tag = COALESCE(?, last_release_tag, '') WHERE repo_id = ?",
            (run_id, now_iso, daily_gain, release_tag, repo_id))

    def set_gain_baseline(self, repo_id: int, daily_gain: float) -> None:
        """已出题仓库第一次被观察到时补基线（日均新增）；已有基线则不改（协助决策 9.10 第 2 条）。"""
        self.conn.execute(
            "UPDATE repos SET gain_at_first_pack = ? WHERE repo_id = ? AND gain_at_first_pack IS NULL",
            (daily_gain, repo_id))

    def set_direction(self, repo_id: int, direction: str) -> None:
        self.conn.execute("UPDATE repos SET direction = ? WHERE repo_id = ?", (direction, repo_id))

    def set_questioned_baseline(self, repo_id: int, direction: str, release_tag: str) -> None:
        """已出题仓库的基线：只在字段为空时写入（方向；上次记录的 release，无则为空字符串）。"""
        self.conn.execute(
            "UPDATE repos SET direction = COALESCE(direction, ?), "
            "last_release_tag = COALESCE(last_release_tag, ?) WHERE repo_id = ?",
            (direction, release_tag, repo_id))

    def questioned_in_direction(self, direction: str, exclude_repo_id: int, limit: int) -> list[dict]:
        """同方向的已出题仓库，按出题时间从近到远（M5.5 对比项目）。"""
        rows = self.conn.execute(
            "SELECT * FROM repos WHERE status = 'questioned' AND direction = ? AND repo_id != ? "
            "ORDER BY questioned_at DESC LIMIT ?", (direction, exclude_repo_id, limit)).fetchall()
        return [dict(r) for r in rows]

    # ---- candidate_gains（M4.3：先写入、后计算基线）----
    def add_candidate_gain(self, run_id: str, repo_id: int, lang_group: str, gain: int,
                           days: int, recorded_at: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO candidate_gains(run_id, repo_id, lang_group, gain, days, recorded_at) "
            "VALUES(?, ?, ?, ?, ?, ?)", (run_id, repo_id, lang_group, int(gain), int(days), recorded_at))

    def baseline_rows(self, since_iso: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT lang_group, gain, days FROM candidate_gains "
            "WHERE recorded_at >= ? AND days > 0", (since_iso,)).fetchall()
        return [dict(r) for r in rows]

    def delete_candidate_gains(self, run_id: str) -> None:
        """运行失败（partial/failed）时删除本次记录，不污染基线。"""
        self.conn.execute("DELETE FROM candidate_gains WHERE run_id = ?", (run_id,))

    # ---- snapshots（Star 快照，只追加，不覆盖；第 9.7 节 (b)）----
    def add_snapshot(self, repo_id: int, stars: int, taken_at: str) -> None:
        self.conn.execute(
            "INSERT INTO snapshots(repo_id, stars, taken_at) VALUES(?, ?, ?)",
            (repo_id, int(stars), taken_at))

    def latest_snapshot(self, repo_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT repo_id, stars, taken_at FROM snapshots WHERE repo_id = ? "
            "ORDER BY snapshot_id DESC LIMIT 1", (repo_id,)).fetchone()
        return dict(row) if row else None

    # ---- enrich_cache ----
    def cache_get(self, repo_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM enrich_cache WHERE repo_id = ?", (repo_id,)).fetchone()
        if not row:
            return None
        return {"run_id": row["run_id"], "fetched_at": row["fetched_at"],
                "payload": json.loads(row["payload"])}

    def cache_put(self, repo_id: int, run_id: str, fetched_at: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT INTO enrich_cache(repo_id, run_id, fetched_at, payload) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(repo_id) DO UPDATE SET run_id = excluded.run_id, "
            "fetched_at = excluded.fetched_at, payload = excluded.payload",
            (repo_id, run_id, fetched_at, json.dumps(payload, ensure_ascii=False)))
