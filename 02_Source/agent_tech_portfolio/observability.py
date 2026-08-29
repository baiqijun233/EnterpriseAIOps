"""可选可观测性适配：本地 JSON 日志、Loki 日志和 Jaeger 链路。"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Mapping
from urllib.request import Request, urlopen


class Observability:
    def __init__(self, log_path: str | Path | None = None, loki_url: str = "", jaeger_url: str = "") -> None:
        self.log_path = Path(log_path) if log_path else None
        self.loki_url = loki_url.strip()
        self.jaeger_url = jaeger_url.strip()

    def record(self, event: Mapping[str, Any]) -> None:
        if not isinstance(event, Mapping):
            raise ValueError("event 必须是对象")
        payload = dict(event)
        payload.setdefault("event_id", uuid.uuid4().hex)
        payload.setdefault("timestamp", time.time())
        line = json.dumps(payload, ensure_ascii=False)
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        if self.loki_url:
            self._post_json(self.loki_url, {
                "streams": [{"stream": {"source": "aiops"}, "values": [[str(int(payload["timestamp"] * 1_000_000_000)), line]]}]
            })

    def trace(self, name: str, trace_id: str, attributes: Mapping[str, Any] | None = None) -> None:
        if not name or not trace_id:
            raise ValueError("name 和 trace_id 不能为空")
        payload = {"name": name, "trace_id": trace_id, "attributes": dict(attributes or {})}
        self.record({"type": "span", **payload})
        if self.jaeger_url:
            self._post_json(self.jaeger_url, {"resourceSpans": [{"scopeSpans": [{"spans": [{"name": name, "traceId": trace_id[:32].ljust(32, "0"), "spanId": uuid.uuid4().hex[:16], "attributes": [{"key": str(k), "value": {"stringValue": str(v)}} for k, v in dict(attributes or {}).items()]}]}]}]})

    def health_check(self, timeout: float = 2.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout 必须是正数")

    def close(self) -> None:
        return

    @staticmethod
    def _post_json(url: str, payload: Mapping[str, Any]) -> None:
        request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=5) as response:
            if response.status >= 300:
                raise RuntimeError(f"可观测性服务返回 HTTP {response.status}")
