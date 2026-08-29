"""Redis 和 Celery 异步任务分发适配器。"""

from __future__ import annotations

import json
from typing import Any, Callable


def _validate_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("任务 payload 必须是对象")
    try:
        json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"任务 payload 不可 JSON 序列化: {exc}") from exc


class RedisTaskQueue:
    def __init__(self, url: str = "redis://localhost:6379/0", client_factory: Callable[..., Any] | None = None) -> None:
        if not isinstance(url, str) or not url.startswith("redis://"):
            raise ValueError("url 必须是 redis:// 地址")
        self.url = url
        self._client_factory = client_factory
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self._client_factory is not None:
            self._client = self._client_factory(self.url)
            return self._client
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("Redis 模式需要安装 redis：python -m pip install redis") from exc
        self._client = redis.Redis.from_url(self.url, decode_responses=True)
        return self._client

    def enqueue(self, queue: str, payload: dict[str, Any]) -> None:
        if not isinstance(queue, str) or not queue.strip():
            raise ValueError("queue 不能为空")
        _validate_payload(payload)
        self._get_client().rpush(queue.strip(), json.dumps(payload, ensure_ascii=False))

    def dequeue(self, queue: str, timeout: int = 1) -> dict[str, Any] | None:
        if not isinstance(queue, str) or not queue.strip():
            raise ValueError("queue 不能为空")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 0:
            raise ValueError("timeout 必须是非负整数")
        result = self._get_client().blpop(queue.strip(), timeout=timeout)
        if result is None:
            return None
        raw = result[1] if isinstance(result, (tuple, list)) else result
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Redis 任务格式错误: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Redis 任务 payload 必须是对象")
        return payload

    def close(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            self._client.close()


class CeleryTaskDispatcher:
    def __init__(self, broker_url: str, app_factory: Callable[..., Any] | None = None) -> None:
        if not isinstance(broker_url, str) or not broker_url.startswith(("redis://", "rediss://", "amqp://")):
            raise ValueError("broker_url 必须是 redis://、rediss:// 或 amqp:// 地址")
        self.broker_url = broker_url
        self._app_factory = app_factory
        self._app: Any | None = None

    def _get_app(self) -> Any:
        if self._app is not None:
            return self._app
        if self._app_factory is not None:
            self._app = self._app_factory(self.broker_url)
            return self._app
        try:
            from celery import Celery
        except ImportError as exc:
            raise RuntimeError("Celery 模式需要安装 celery：python -m pip install celery") from exc
        self._app = Celery("aiops", broker=self.broker_url)
        return self._app

    def dispatch(self, task_name: str, payload: dict[str, Any]) -> str:
        if not isinstance(task_name, str) or not task_name.strip():
            raise ValueError("task_name 不能为空")
        _validate_payload(payload)
        result = self._get_app().send_task(task_name.strip(), kwargs=payload)
        task_id = getattr(result, "id", None)
        if not task_id:
            raise RuntimeError("Celery 未返回任务 ID")
        return str(task_id)

    def close(self) -> None:
        return
