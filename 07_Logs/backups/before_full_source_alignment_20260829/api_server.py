"""标准库 HTTP API：用于离线演示多 Agent 运维流程。"""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from aiops_agent import AIOpsOrchestrator, Alert, load_topology
from auth import AuthManager, AuthenticationError, AuthorizationError, AuthPrincipal
from event_bus import create_event_bus
from llm_adapter import DeepSeekLLMClient, DeterministicLLMClient, OpenAICompatibleLLMClient
from metrics import MetricsRegistry
from repair_executor import AllowlistRepairExecutor, DryRunRepairExecutor
from readiness import ReadinessChecker
from common.storage import TaskStore, record_to_dict
from adapters.neo4j_topology import Neo4jTopologyProvider


def build_orchestrator() -> AIOpsOrchestrator:
    configured_data_path = os.getenv("AIOPS_DATA_DIR", "").strip()
    data_path = Path(configured_data_path) if configured_data_path else Path(__file__).resolve().parents[2] / "04_Data"
    topology_path = data_path / "topology.json"
    topology_mode = os.getenv("AIOPS_TOPOLOGY", "json").strip().lower()
    if topology_mode == "neo4j":
        topology = Neo4jTopologyProvider(
            uri=os.getenv("AIOPS_NEO4J_URI", "bolt://localhost:7687"),
            user=os.getenv("AIOPS_NEO4J_USER", "neo4j"),
            password=os.getenv("AIOPS_NEO4J_PASSWORD", "aiops_password"),
        )
    elif topology_mode == "json":
        try:
            topology = load_topology(topology_path)
        except (FileNotFoundError, ValueError):
            topology = None
    else:
        raise ValueError("AIOPS_TOPOLOGY 只能是 json 或 neo4j")
    bus_mode = os.getenv("AIOPS_EVENT_BUS", "memory").strip().lower()
    if bus_mode not in {"memory", "kafka"}:
        raise ValueError("AIOPS_EVENT_BUS 只能是 memory 或 kafka")
    event_bus = create_event_bus(
        use_kafka=bus_mode == "kafka",
        bootstrap_servers=os.getenv("AIOPS_KAFKA_BOOTSTRAP", "localhost:9092"),
    )
    llm_mode = os.getenv("AIOPS_LLM", "auto").strip().lower()
    if llm_mode == "auto":
        # 有 DeepSeek 密钥时优先使用；没有密钥时保持离线可运行。
        llm_mode = "deepseek" if os.getenv("AIOPS_DEEPSEEK_API_KEY", "").strip() else "none"
    if llm_mode == "deterministic":
        llm_client = DeterministicLLMClient()
    elif llm_mode == "deepseek":
        llm_client = DeepSeekLLMClient(
            api_key=os.getenv("AIOPS_DEEPSEEK_API_KEY", ""),
            endpoint=os.getenv("AIOPS_DEEPSEEK_ENDPOINT", DeepSeekLLMClient.DEFAULT_ENDPOINT),
            model=os.getenv("AIOPS_DEEPSEEK_MODEL", DeepSeekLLMClient.DEFAULT_MODEL),
        )
    elif llm_mode == "openai":
        llm_client = OpenAICompatibleLLMClient(
            endpoint=os.getenv("AIOPS_LLM_ENDPOINT", ""),
            api_key=os.getenv("AIOPS_LLM_API_KEY", ""),
            model=os.getenv("AIOPS_LLM_MODEL", ""),
        )
    elif llm_mode == "none":
        llm_client = None
    else:
        raise ValueError("AIOPS_LLM 只能是 auto、none、deterministic、deepseek 或 openai")
    safety_backend = os.getenv("AIOPS_SAFETY_BACKEND", "memory").strip().lower()
    if safety_backend == "redis":
        from adapters.redis_safety import RedisSafetyGuard

        safety_guard = RedisSafetyGuard(
            os.getenv("AIOPS_SAFETY_REDIS_URL", "redis://localhost:6379/0"),
            key_prefix=os.getenv(
                "AIOPS_SAFETY_KEY_PREFIX", "project024:aiops:safety"
            ),
        )
    elif safety_backend == "memory":
        safety_guard = None
    else:
        raise ValueError("AIOPS_SAFETY_BACKEND 只能是 memory 或 redis")
    executor_mode = os.getenv("AIOPS_REPAIR_EXECUTOR", "dry-run").strip().lower()
    if executor_mode in {"dry-run", "dry_run", "none"}:
        repair_executor = DryRunRepairExecutor()
    elif executor_mode == "allowlist":
        raw_commands = os.getenv("AIOPS_REPAIR_COMMANDS", "").strip()
        if not raw_commands:
            raise ValueError("AIOPS_REPAIR_COMMANDS 未配置，无法启用 allowlist 执行器")
        try:
            commands = json.loads(raw_commands)
        except json.JSONDecodeError as exc:
            raise ValueError("AIOPS_REPAIR_COMMANDS 必须是 JSON 对象") from exc
        repair_executor = AllowlistRepairExecutor(
            commands,
            timeout=float(os.getenv("AIOPS_REPAIR_TIMEOUT", "30")),
        )
    else:
        raise ValueError("AIOPS_REPAIR_EXECUTOR 只能是 dry-run 或 allowlist")
    return AIOpsOrchestrator(
        store=TaskStore(database_path=data_path / "aiops_tasks.sqlite3"),
        topology=topology,
        event_bus=event_bus,
        llm_client=llm_client,
        safety_guard=safety_guard,
        repair_executor=repair_executor,
    )


metrics = MetricsRegistry()


class AIOpsRequestHandler(BaseHTTPRequestHandler):
    """将 HTTP 请求转换为编排器调用，保持无第三方依赖。"""

    def do_GET(self) -> None:  # noqa: N802 - 标准库接口名称
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({"status": "healthy"})
            return
        if parsed.path == "/ready":
            readiness = self.server.readiness_checker.check()
            status = (
                HTTPStatus.OK
                if readiness["status"] == "ready"
                else HTTPStatus.SERVICE_UNAVAILABLE
            )
            self._send_json(readiness, status)
            return
        if parsed.path == "/metrics":
            self._send_text(metrics.render(), "text/plain; version=0.0.4")
            return
        if parsed.path == "/api/v1/tasks":
            if self._authorize("viewer") is None:
                return
            query = parse_qs(parsed.query)
            raw_limit = query.get("limit", ["50"])[0]
            try:
                limit = int(raw_limit)
                tasks = [record_to_dict(item) for item in self.server.orchestrator.store.list_recent(limit)]
            except (TypeError, ValueError):
                self._send_json({"error": "limit 必须是 1 到 200 的整数"}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"tasks": tasks})
            return
        if parsed.path.startswith("/api/v1/tasks/"):
            if self._authorize("viewer") is None:
                return
            task_id = parsed.path.rsplit("/", 1)[-1].strip()
            record = self.server.orchestrator.store.get(task_id)
            if record is None:
                self._send_json({"error": "任务不存在"}, HTTPStatus.NOT_FOUND)
                return
            self._send_json(record_to_dict(record))
            return
        self._send_json({"error": "路径不存在"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - 标准库接口名称
        if self.path.startswith("/api/v1/tasks/") and self.path.endswith("/approval"):
            principal = self._authorize("approver")
            if principal is None:
                return
            self._handle_approval(principal)
            return
        if self.path != "/api/v1/incidents":
            self._send_json({"error": "路径不存在"}, HTTPStatus.NOT_FOUND)
            return
        if self._authorize("operator") is None:
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1024 * 1024:
                raise ValueError("请求体大小无效")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("请求体必须是 JSON 对象")
            alert = Alert(
                service=str(payload.get("service", "")).strip(),
                metric=str(payload.get("metric", "")).strip(),
                value=float(payload.get("value")),
                baseline=[float(item) for item in payload.get("baseline", [])],
                severity=str(payload.get("severity", "high")),
            )
            record = self.server.orchestrator.handle(alert)
            metrics.increment("aiops_incidents_created_total")
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self._send_json({"error": f"请求参数无效: {exc}"}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(record_to_dict(record), HTTPStatus.CREATED)

    def _handle_approval(self, principal: AuthPrincipal) -> None:
        task_id = self.path.split("/api/v1/tasks/", 1)[1][:-len("/approval")].strip("/")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1024 * 1024:
                raise ValueError("请求体大小无效")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("请求体必须是 JSON 对象")
            approved = payload.get("approved")
            record = self.server.orchestrator.resume_approval(
                task_id,
                approved,
                actor={
                    "source": "api",
                    "role": principal.role,
                    "id": principal.key_id,
                },
            )
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self._send_json({"error": f"审批参数无效: {exc}"}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(record_to_dict(record))

    def _authorize(self, required_role: str) -> AuthPrincipal | None:
        try:
            return self.server.auth_manager.authorize(
                self.headers.get("X-API-Key"),
                required_role,
            )
        except AuthenticationError as exc:
            self._send_json(
                {"error": str(exc)},
                HTTPStatus.UNAUTHORIZED,
                headers={"WWW-Authenticate": "ApiKey"},
            )
        except AuthorizationError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.FORBIDDEN)
        return None

    def _send_json(
        self,
        data: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        headers: dict[str, str] | None = None,
    ) -> None:
        metrics.increment("aiops_http_responses_total")
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for header_name, header_value in (headers or {}).items():
            self.send_header(header_name, header_value)
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, body: str, content_type: str) -> None:
        metrics.increment("aiops_http_responses_total")
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        return


class AIOpsHTTPServer(ThreadingHTTPServer):
    """为每个 HTTP 服务实例创建并负责释放独立编排器。"""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        auth_manager: AuthManager | None = None,
    ) -> None:
        resolved_auth_manager = (
            auth_manager if auth_manager is not None else AuthManager.from_environment()
        )
        super().__init__(server_address, handler_class)
        self.orchestrator = build_orchestrator()
        self.auth_manager = resolved_auth_manager
        self.readiness_checker = ReadinessChecker(self.orchestrator)

    def server_close(self) -> None:
        try:
            self.orchestrator.close()
        finally:
            super().server_close()


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    auth_manager: AuthManager | None = None,
) -> ThreadingHTTPServer:
    # 允许 0 让操作系统分配临时端口，便于测试和多实例启动。
    if not host or not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
        raise ValueError("host 或 port 无效")
    return AIOpsHTTPServer((host, port), AIOpsRequestHandler, auth_manager=auth_manager)


if __name__ == "__main__":
    server = create_server()
    print("AIOps API 已启动: http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
