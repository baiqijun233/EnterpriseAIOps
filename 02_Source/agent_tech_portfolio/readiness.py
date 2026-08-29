"""统一就绪检查：区分进程存活与依赖可用性。"""

from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable


class ReadinessChecker:
    """检查编排器当前启用的必需依赖，并短时缓存结果。"""

    def __init__(
        self,
        orchestrator: Any,
        cache_seconds: float = 5.0,
        probe_timeout: float = 2.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if orchestrator is None:
            raise ValueError("orchestrator 不能为空")
        if (
            not isinstance(cache_seconds, (int, float))
            or isinstance(cache_seconds, bool)
            or cache_seconds < 0
        ):
            raise ValueError("cache_seconds 必须大于或等于 0")
        if (
            not isinstance(probe_timeout, (int, float))
            or isinstance(probe_timeout, bool)
            or probe_timeout <= 0
        ):
            raise ValueError("probe_timeout 必须大于 0")
        if clock is not None and not callable(clock):
            raise ValueError("clock 必须可调用")
        self.orchestrator = orchestrator
        self.cache_seconds = float(cache_seconds)
        self.probe_timeout = float(probe_timeout)
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._cached_at = float("-inf")
        self._cached_result: dict[str, Any] | None = None

    def check(self) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            if (
                self._cached_result is not None
                and now - self._cached_at < self.cache_seconds
            ):
                return copy.deepcopy(self._cached_result)
            result = self._run_checks()
            self._cached_result = result
            self._cached_at = now
            return copy.deepcopy(result)

    def _run_checks(self) -> dict[str, Any]:
        checks = {
            "storage": self._probe_required(
                getattr(self.orchestrator, "store", None),
                mode="sqlite",
            ),
            "event_bus": self._probe_required(
                getattr(self.orchestrator, "event_bus", None),
                mode=self._component_name(getattr(self.orchestrator, "event_bus", None)),
            ),
            "topology": self._check_topology(),
            "llm": self._check_llm(),
        }
        required_names = ("storage", "event_bus", "topology")
        is_ready = all(checks[name]["status"] == "ready" for name in required_names)
        return {
            "status": "ready" if is_ready else "not_ready",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "cache_seconds": self.cache_seconds,
            "checks": checks,
        }

    def _probe_required(self, component: Any, mode: str) -> dict[str, Any]:
        if component is None:
            return {
                "status": "not_ready",
                "mode": mode,
                "error_type": "MissingDependency",
            }
        health_check = getattr(component, "health_check", None)
        if not callable(health_check):
            return {
                "status": "not_ready",
                "mode": mode,
                "error_type": "HealthCheckUnavailable",
            }
        started_at = self._clock()
        try:
            health_check(timeout=self.probe_timeout)
        except Exception as exc:
            return {
                "status": "not_ready",
                "mode": mode,
                "latency_ms": self._latency_ms(started_at),
                "error_type": type(exc).__name__,
            }
        return {
            "status": "ready",
            "mode": mode,
            "latency_ms": self._latency_ms(started_at),
        }

    def _check_topology(self) -> dict[str, Any]:
        topology = getattr(getattr(self.orchestrator, "rca", None), "topology", None)
        if isinstance(topology, dict):
            return {
                "status": "ready",
                "mode": "json",
                "service_count": len(topology),
            }
        return self._probe_required(topology, mode=self._component_name(topology))

    def _check_llm(self) -> dict[str, Any]:
        llm_client = getattr(getattr(self.orchestrator, "rca", None), "llm_client", None)
        if llm_client is None:
            return {"status": "disabled", "mode": "none"}
        mode = self._component_name(llm_client)
        if mode == "DeterministicLLMClient":
            return {"status": "ready", "mode": mode, "probe": "local"}
        return {
            "status": "ready",
            "mode": mode,
            "probe": "configuration_only",
        }

    def _latency_ms(self, started_at: float) -> float:
        return round(max(0.0, self._clock() - started_at) * 1000, 3)

    @staticmethod
    def _component_name(component: Any) -> str:
        return type(component).__name__ if component is not None else "missing"
