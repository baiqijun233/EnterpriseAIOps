"""Celery 任务入口，用于验证 Redis Broker 到 Worker 的完整链路。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Celery Worker 可能从任意工作目录启动，按入口文件位置确保项目模块可导入。
SOURCE_DIR = str(Path(__file__).resolve().parent)
if SOURCE_DIR not in sys.path:
    sys.path.insert(0, SOURCE_DIR)

from aiops_agent import Alert
from common.storage import record_to_dict


def create_celery_app() -> Any:
    try:
        from celery import Celery
    except ImportError as exc:
        raise RuntimeError(
            "Celery 模式需要安装依赖：python -m pip install -r requirements-production.txt"
        ) from exc
    broker_url = os.getenv("AIOPS_CELERY_BROKER", "redis://localhost:6379/0")
    if not broker_url.startswith(("redis://", "rediss://", "amqp://")):
        raise ValueError("AIOPS_CELERY_BROKER 必须是 redis、rediss 或 amqp 地址")
    app = Celery("aiops", broker=broker_url, backend=broker_url)
    app.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json")

    @app.task(name="aiops.echo")
    def echo(payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        """兼容 Celery 的 kwargs 分发方式，便于复用 CeleryTaskDispatcher。"""
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("payload 必须是对象")
        if payload is not None and kwargs:
            raise ValueError("payload 和展开参数不能同时传入")
        task_payload = payload if payload is not None else kwargs
        return {"status": "processed", "payload": task_payload}

    @app.task(name="aiops.handle_incident")
    def handle_incident(
        service: str,
        metric: str,
        value: float,
        baseline: list[float],
        severity: str = "high",
    ) -> dict[str, Any]:
        """在 Worker 内执行一条完整的 AIOps 告警流程。"""
        from api_server import build_orchestrator

        orchestrator = build_orchestrator()
        try:
            record = orchestrator.handle(Alert(service, metric, value, baseline, severity))
            return record_to_dict(record)
        finally:
            orchestrator.close()

    return app


celery_app = create_celery_app()
