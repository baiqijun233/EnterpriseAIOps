"""FastAPI 正式入口，依赖按需加载，默认离线 HTTP 服务不受影响。"""

from typing import Any


def create_app(orchestrator: Any | None = None) -> Any:
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import PlainTextResponse
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError(
            "FastAPI 模式需要安装依赖：python -m pip install -r requirements-fastapi.txt"
        ) from exc

    if orchestrator is None:
        from api_server import build_orchestrator

        orchestrator = build_orchestrator()

    class IncidentRequest(BaseModel):
        service: str
        metric: str
        value: float
        baseline: list[float] = Field(default_factory=list)
        severity: str = "high"

    class ApprovalRequest(BaseModel):
        approved: bool

    app = FastAPI(
        title="Enterprise Multi-Agent AIOps",
        version="1.0.0",
        description="企业级多 Agent 智能运维系统 API",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        from metrics import MetricsRegistry

        registry = MetricsRegistry()
        registry.increment("aiops_fastapi_requests_total")
        return registry.render()

    @app.post("/api/v1/incidents", status_code=201)
    def create_incident(request: IncidentRequest) -> dict[str, Any]:
        from aiops_agent import Alert
        from common.storage import record_to_dict

        try:
            record = orchestrator.handle(Alert(
                service=request.service.strip(),
                metric=request.metric.strip(),
                value=request.value,
                baseline=request.baseline,
                severity=request.severity,
            ))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return record_to_dict(record)

    @app.get("/api/v1/tasks")
    def list_tasks(limit: int = 50) -> dict[str, Any]:
        from common.storage import record_to_dict

        try:
            tasks = [record_to_dict(item) for item in orchestrator.store.list_recent(limit)]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"tasks": tasks}

    @app.get("/api/v1/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        from common.storage import record_to_dict

        record = orchestrator.store.get(task_id.strip())
        if record is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return record_to_dict(record)

    @app.post("/api/v1/tasks/{task_id}/approval")
    def approve_task(task_id: str, request: ApprovalRequest) -> dict[str, Any]:
        from common.storage import record_to_dict

        try:
            record = orchestrator.resume_approval(task_id.strip(), request.approved)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return record_to_dict(record)

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
