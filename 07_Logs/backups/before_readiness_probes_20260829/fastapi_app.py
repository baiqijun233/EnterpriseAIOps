"""FastAPI 正式入口，依赖按需加载，默认离线 HTTP 服务不受影响。"""

from contextlib import asynccontextmanager
from typing import Any


def create_app(orchestrator: Any | None = None, auth_manager: Any | None = None) -> Any:
    try:
        from fastapi import Depends, FastAPI, HTTPException
        from fastapi.responses import PlainTextResponse
        from fastapi.security import APIKeyHeader
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError(
            "FastAPI 模式需要安装依赖：python -m pip install -r requirements-fastapi.txt"
        ) from exc

    owns_orchestrator = orchestrator is None
    if auth_manager is None:
        from auth import AuthManager

        auth_manager = AuthManager.from_environment()
    if owns_orchestrator:
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

    @asynccontextmanager
    async def lifespan(app: Any):
        yield
        if owns_orchestrator and hasattr(orchestrator, "close"):
            orchestrator.close()

    app = FastAPI(
        title="Enterprise Multi-Agent AIOps",
        version="1.1.0",
        description="企业级多 Agent 智能运维系统 API",
        lifespan=lifespan,
    )
    app.state.auth_manager = auth_manager

    from auth import AuthenticationError, AuthorizationError
    from metrics import MetricsRegistry

    metrics_registry = MetricsRegistry()
    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def require_role(required_role: str) -> Any:
        def authorize(api_key: str | None = Depends(api_key_header)) -> Any:
            try:
                return auth_manager.authorize(api_key, required_role)
            except AuthenticationError as exc:
                raise HTTPException(
                    status_code=401,
                    detail=str(exc),
                    headers={"WWW-Authenticate": "ApiKey"},
                ) from exc
            except AuthorizationError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc

        return authorize

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        metrics_registry.increment("aiops_fastapi_requests_total")
        return metrics_registry.render()

    @app.post(
        "/api/v1/incidents",
        status_code=201,
        dependencies=[Depends(require_role("operator"))],
    )
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

    @app.get("/api/v1/tasks", dependencies=[Depends(require_role("viewer"))])
    def list_tasks(limit: int = 50) -> dict[str, Any]:
        from common.storage import record_to_dict

        try:
            tasks = [record_to_dict(item) for item in orchestrator.store.list_recent(limit)]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"tasks": tasks}

    @app.get(
        "/api/v1/tasks/{task_id}",
        dependencies=[Depends(require_role("viewer"))],
    )
    def get_task(task_id: str) -> dict[str, Any]:
        from common.storage import record_to_dict

        record = orchestrator.store.get(task_id.strip())
        if record is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return record_to_dict(record)

    @app.post("/api/v1/tasks/{task_id}/approval")
    def approve_task(
        task_id: str,
        request: ApprovalRequest,
        principal: Any = Depends(require_role("approver")),
    ) -> dict[str, Any]:
        from common.storage import record_to_dict

        try:
            record = orchestrator.resume_approval(
                task_id.strip(),
                request.approved,
                actor={
                    "source": "api",
                    "role": principal.role,
                    "id": principal.key_id,
                },
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return record_to_dict(record)

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
