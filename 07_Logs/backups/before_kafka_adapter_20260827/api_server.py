"""标准库 HTTP API：用于离线演示多 Agent 运维流程。"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from aiops_agent import AIOpsOrchestrator, Alert, load_topology
from common.storage import TaskStore, record_to_dict


def build_orchestrator() -> AIOpsOrchestrator:
    data_path = Path(__file__).resolve().parents[2] / "04_Data"
    topology_path = data_path / "topology.json"
    try:
        topology = load_topology(topology_path)
    except (FileNotFoundError, ValueError):
        topology = None
    return AIOpsOrchestrator(
        store=TaskStore(database_path=data_path / "aiops_tasks.sqlite3"),
        topology=topology,
    )


class AIOpsRequestHandler(BaseHTTPRequestHandler):
    """将 HTTP 请求转换为编排器调用，保持无第三方依赖。"""

    orchestrator = build_orchestrator()

    def do_GET(self) -> None:  # noqa: N802 - 标准库接口名称
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({"status": "healthy"})
            return
        if parsed.path == "/api/v1/tasks":
            query = parse_qs(parsed.query)
            raw_limit = query.get("limit", ["50"])[0]
            try:
                limit = int(raw_limit)
                tasks = [record_to_dict(item) for item in self.orchestrator.store.list_recent(limit)]
            except (TypeError, ValueError):
                self._send_json({"error": "limit 必须是 1 到 200 的整数"}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"tasks": tasks})
            return
        if parsed.path.startswith("/api/v1/tasks/"):
            task_id = parsed.path.rsplit("/", 1)[-1].strip()
            record = self.orchestrator.store.get(task_id)
            if record is None:
                self._send_json({"error": "任务不存在"}, HTTPStatus.NOT_FOUND)
                return
            self._send_json(record_to_dict(record))
            return
        self._send_json({"error": "路径不存在"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - 标准库接口名称
        if self.path.startswith("/api/v1/tasks/") and self.path.endswith("/approval"):
            self._handle_approval()
            return
        if self.path != "/api/v1/incidents":
            self._send_json({"error": "路径不存在"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1024 * 1024:
                raise ValueError("请求体大小无效")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            alert = Alert(
                service=str(payload.get("service", "")).strip(),
                metric=str(payload.get("metric", "")).strip(),
                value=float(payload.get("value")),
                baseline=[float(item) for item in payload.get("baseline", [])],
                severity=str(payload.get("severity", "high")),
            )
            record = self.orchestrator.handle(alert)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self._send_json({"error": f"请求参数无效: {exc}"}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(record_to_dict(record), HTTPStatus.CREATED)

    def _handle_approval(self) -> None:
        task_id = self.path.split("/api/v1/tasks/", 1)[1][:-len("/approval")].strip("/")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            approved = payload.get("approved")
            record = self.orchestrator.resume_approval(task_id, approved)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self._send_json({"error": f"审批参数无效: {exc}"}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(record_to_dict(record))

    def _send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def create_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    # 允许 0 让操作系统分配临时端口，便于测试和多实例启动。
    if not host or not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
        raise ValueError("host 或 port 无效")
    return ThreadingHTTPServer((host, port), AIOpsRequestHandler)


if __name__ == "__main__":
    server = create_server()
    print("AIOps API 已启动: http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        AIOpsRequestHandler.orchestrator.store.close()
