"""CMDB 适配器：离线 JSON 与 HTTP 两种实现。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


class JsonCMDB:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._data: dict[str, dict[str, Any]] = {}
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("CMDB JSON 必须是对象")
            self._data = {str(k): v for k, v in data.items() if isinstance(v, dict)}

    def get_service(self, service: str) -> dict[str, Any]:
        if not service:
            raise ValueError("service 不能为空")
        return dict(self._data.get(service, {"name": service, "environment": "unknown"}))

    def health_check(self, timeout: float = 2.0) -> None:
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout 必须是正数")

    def close(self) -> None:
        return


class HttpCMDB:
    def __init__(self, base_url: str, timeout: float = 2.0) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url 必须是 HTTP 地址")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_service(self, service: str) -> dict[str, Any]:
        if not service:
            raise ValueError("service 不能为空")
        request = Request(f"{self.base_url}/services/{service}", method="GET")
        with urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("CMDB 返回必须是对象")
        return data

    def health_check(self, timeout: float = 2.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout 必须是正数")

    def close(self) -> None:
        return
