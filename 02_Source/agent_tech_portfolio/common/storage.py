"""Small SQLite task store used by both demos."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskRecord:
    task_id: str
    task_type: str
    status: str
    state: dict[str, Any]
    updated_at: str


class TaskStore:
    """Thread-safe persistence with explicit status transitions."""

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        self.database_path = str(database_path)
        self._lock = threading.RLock()
        self._closed = False
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def save(self, record: TaskRecord) -> None:
        if not record.task_id or not record.task_type or not record.status:
            raise ValueError("task_id、task_type 和 status 不能为空")
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO tasks(task_id, task_type, status, state_json, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    task_type=excluded.task_type,
                    status=excluded.status,
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (record.task_id, record.task_type, record.status, json.dumps(record.state, ensure_ascii=False), record.updated_at),
            )
            self._connection.commit()

    def get(self, task_id: str) -> TaskRecord | None:
        if not task_id:
            return None
        with self._lock:
            row = self._connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return TaskRecord(row["task_id"], row["task_type"], row["status"], json.loads(row["state_json"]), row["updated_at"])

    def save_if_status(self, record: TaskRecord, expected_status: str) -> bool:
        """仅在数据库中状态仍符合预期时更新，保证多进程审批幂等。"""
        if not record.task_id or not record.task_type or not record.status or not expected_status:
            raise ValueError("task_id、task_type、status 和 expected_status 不能为空")
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE tasks
                SET task_type = ?, status = ?, state_json = ?, updated_at = ?
                WHERE task_id = ? AND status = ?
                """,
                (
                    record.task_type,
                    record.status,
                    json.dumps(record.state, ensure_ascii=False),
                    record.updated_at,
                    record.task_id,
                    expected_status,
                ),
            )
            self._connection.commit()
            return cursor.rowcount == 1

    def list_recent(self, limit: int = 50) -> list[TaskRecord]:
        """按更新时间倒序返回最近任务，供接口查询使用。"""
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit 必须是整数")
        limit = max(1, min(limit, 200))
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            TaskRecord(
                row["task_id"],
                row["task_type"],
                row["status"],
                json.loads(row["state_json"]),
                row["updated_at"],
            )
            for row in rows
        ]

    def health_check(self, timeout: float = 2.0) -> None:
        """执行只读 SQL，确认 SQLite 连接可用。"""
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("timeout 必须是正数")
        with self._lock:
            row = self._connection.execute("SELECT 1 AS healthy").fetchone()
        if row is None or row["healthy"] != 1:
            raise RuntimeError("SQLite 就绪检查失败")

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True


class PostgresTaskStore:
    """PostgreSQL 任务存储；仅在 AIOPS_STORAGE=postgres 时加载驱动。"""

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("database_url 必须是 PostgreSQL 地址")
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("PostgreSQL 模式需要安装 psycopg[binary]") from exc
        self.database_path = database_url
        self._connection = psycopg.connect(database_url, autocommit=True)
        self._closed = False
        with self._connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    state_json JSONB NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def save(self, record: TaskRecord) -> None:
        _validate_record(record)
        with self._connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO tasks(task_id, task_type, status, state_json, updated_at)
                VALUES(%s, %s, %s, %s::jsonb, %s)
                ON CONFLICT(task_id) DO UPDATE SET task_type=EXCLUDED.task_type,
                status=EXCLUDED.status, state_json=EXCLUDED.state_json, updated_at=EXCLUDED.updated_at
            """, (record.task_id, record.task_type, record.status, json.dumps(record.state, ensure_ascii=False), record.updated_at))

    def get(self, task_id: str) -> TaskRecord | None:
        if not task_id:
            return None
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT task_id, task_type, status, state_json, updated_at FROM tasks WHERE task_id=%s", (task_id,))
            row = cursor.fetchone()
        return TaskRecord(row[0], row[1], row[2], row[3] if isinstance(row[3], dict) else json.loads(row[3]), row[4]) if row else None

    def save_if_status(self, record: TaskRecord, expected_status: str) -> bool:
        _validate_record(record)
        if not expected_status:
            raise ValueError("expected_status 不能为空")
        with self._connection.cursor() as cursor:
            cursor.execute("UPDATE tasks SET task_type=%s,status=%s,state_json=%s::jsonb,updated_at=%s WHERE task_id=%s AND status=%s", (record.task_type, record.status, json.dumps(record.state, ensure_ascii=False), record.updated_at, record.task_id, expected_status))
            return cursor.rowcount == 1

    def list_recent(self, limit: int = 50) -> list[TaskRecord]:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit 必须是整数")
        limit = max(1, min(limit, 200))
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT task_id, task_type, status, state_json, updated_at FROM tasks ORDER BY updated_at DESC LIMIT %s", (limit,))
            rows = cursor.fetchall()
        return [TaskRecord(row[0], row[1], row[2], row[3] if isinstance(row[3], dict) else json.loads(row[3]), row[4]) for row in rows]

    def health_check(self, timeout: float = 2.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout 必须是正数")
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone()[0] != 1:
                raise RuntimeError("PostgreSQL 就绪检查失败")

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True


def _validate_record(record: TaskRecord) -> None:
    if not record.task_id or not record.task_type or not record.status:
        raise ValueError("task_id、task_type 和 status 不能为空")


def record_to_dict(record: TaskRecord) -> dict[str, Any]:
    return asdict(record)
