"""Celery Worker 就绪检查，可作为部署健康命令。"""

from __future__ import annotations

import json
from typing import Any


def check_worker(
    app: Any | None = None,
    timeout: float = 2.0,
    required_task: str = "aiops.handle_incident",
) -> dict[str, Any]:
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError("timeout 必须是正数")
    if not isinstance(required_task, str) or not required_task.strip():
        raise ValueError("required_task 不能为空")
    try:
        if app is None:
            from celery_app import celery_app

            app = celery_app
        inspector = app.control.inspect(timeout=float(timeout))
        registrations = inspector.registered() or {}
    except Exception as exc:
        return {"status": "not_ready", "workers": [], "error_type": type(exc).__name__}
    if not isinstance(registrations, dict):
        return {
            "status": "not_ready",
            "workers": [],
            "error_type": "InvalidWorkerResponse",
        }
    worker_names = sorted(
        str(worker_name)
        for worker_name, task_names in registrations.items()
        if isinstance(task_names, (list, tuple, set)) and required_task.strip() in task_names
    )
    return {
        "status": "ready" if worker_names else "not_ready",
        "workers": worker_names,
        "required_task": required_task.strip(),
    }


def main() -> int:
    result = check_worker()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
