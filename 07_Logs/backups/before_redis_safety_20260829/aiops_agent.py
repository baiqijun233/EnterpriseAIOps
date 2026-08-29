"""Enterprise-style AIOps orchestration core with local deterministic inputs."""

from __future__ import annotations

import math
import json
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from event_bus import EventBus, InMemoryEventBus
from llm_adapter import LLMClient
from common.storage import TaskRecord, TaskStore, utc_now


@dataclass
class Alert:
    service: str
    metric: str
    value: float
    baseline: list[float]
    severity: str = "high"


def load_topology(path: str | Path) -> dict[str, list[str]]:
    """加载服务拓扑配置，并拒绝不符合约定的数据。"""
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"拓扑文件不存在: {config_path}")
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"拓扑文件读取失败: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("拓扑配置必须是对象")
    topology: dict[str, list[str]] = {}
    for service, dependencies in data.items():
        if not isinstance(service, str) or not service.strip():
            raise ValueError("拓扑服务名不能为空")
        if not isinstance(dependencies, list) or any(
            not isinstance(item, str) or not item.strip() for item in dependencies
        ):
            raise ValueError(f"拓扑依赖必须是字符串列表: {service}")
        topology[service.strip()] = [item.strip() for item in dependencies]
    return topology


class ThreeSigmaDetector:
    def detect(self, alert: Alert) -> bool:
        if not alert.baseline:
            return False
        mean = sum(alert.baseline) / len(alert.baseline)
        variance = sum((item - mean) ** 2 for item in alert.baseline) / len(alert.baseline)
        std = math.sqrt(variance)
        return alert.value > mean + 3 * max(std, 1e-9)


class EwmaDetector:
    def __init__(self, alpha: float = 0.35) -> None:
        if not 0 < alpha <= 1:
            raise ValueError("alpha 必须在 (0, 1] 范围内")
        self.alpha = alpha

    def detect(self, alert: Alert) -> bool:
        if not alert.baseline:
            return False
        ewma = alert.baseline[0]
        for value in alert.baseline[1:]:
            ewma = self.alpha * value + (1 - self.alpha) * ewma
        return alert.value > ewma * 1.2


class MonitorAgent:
    def __init__(self) -> None:
        self.detectors = (ThreeSigmaDetector(), EwmaDetector())

    def confirm(self, alert: Alert) -> dict[str, Any]:
        votes = [detector.detect(alert) for detector in self.detectors]
        return {"confirmed": sum(votes) >= 2, "votes": votes, "alert": alert.__dict__}


class RcaAgent:
    def __init__(self, topology: Any | None = None, llm_client: LLMClient | None = None) -> None:
        self.topology = topology or {}
        self.llm_client = llm_client

    def analyze(self, service: str, alert: dict[str, Any]) -> dict[str, Any]:
        if not service:
            raise ValueError("service 不能为空")
        visited: set[str] = set()
        queue = [service]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            queue.extend(self._dependencies(current))
        related = sorted(visited)
        confidence = 0.72 if len(related) > 1 else 0.48
        result = {
            "service": service,
            "root_cause": f"{service} 近期指标异常",
            "confidence": confidence,
            "impact_chain": related,
            "evidence": alert,
        }
        if self.llm_client is not None:
            try:
                result["explanation"] = self.llm_client.generate(
                    "请基于结构化证据给出简短根因解释，不要编造不存在的事实。",
                    {"service": service, "confidence": confidence, "impact_chain": related},
                )
            except Exception as exc:
                result["llm_error"] = str(exc)
        return result

    def _dependencies(self, service: str) -> list[str]:
        if hasattr(self.topology, "get_dependencies"):
            return list(self.topology.get_dependencies(service))
        return list(self.topology.get(service, []))


class SlidingWindowRateLimiter:
    """按服务限制自动修复频率，避免异常风暴触发连续变更。"""

    def __init__(
        self,
        max_actions: int = 5,
        window_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not isinstance(max_actions, int) or isinstance(max_actions, bool) or max_actions < 1:
            raise ValueError("max_actions 必须是正整数")
        if not isinstance(window_seconds, (int, float)) or window_seconds <= 0:
            raise ValueError("window_seconds 必须大于 0")
        self.max_actions = max_actions
        self.window_seconds = float(window_seconds)
        self._clock = clock or time.monotonic
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.RLock()

    def allow(self, service: str) -> bool:
        if not service:
            raise ValueError("service 不能为空")
        now = self._clock()
        cutoff = now - self.window_seconds
        with self._lock:
            events = self._events[service]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.max_actions:
                return False
            events.append(now)
            return True


class CircuitBreaker:
    """按服务记录修复失败，超过阈值后暂停自动修复。"""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not isinstance(failure_threshold, int) or isinstance(failure_threshold, bool) or failure_threshold < 1:
            raise ValueError("failure_threshold 必须是正整数")
        if not isinstance(recovery_seconds, (int, float)) or recovery_seconds <= 0:
            raise ValueError("recovery_seconds 必须大于 0")
        self.failure_threshold = failure_threshold
        self.recovery_seconds = float(recovery_seconds)
        self._clock = clock or time.monotonic
        self._states: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def allow(self, service: str) -> bool:
        if not service:
            raise ValueError("service 不能为空")
        with self._lock:
            state = self._state_for(service)
            if state["state"] == "closed":
                return True
            if state["state"] == "open":
                opened_at = float(state["opened_at"])
                if self._clock() - opened_at < self.recovery_seconds:
                    return False
                state["state"] = "half_open"
                state["probe_in_flight"] = True
                return True
            return False

    def record_failure(self, service: str) -> None:
        if not service:
            raise ValueError("service 不能为空")
        with self._lock:
            state = self._state_for(service)
            state["failure_count"] += 1
            if state["state"] == "half_open" or state["failure_count"] >= self.failure_threshold:
                state.update({
                    "state": "open",
                    "opened_at": self._clock(),
                    "probe_in_flight": False,
                })

    def record_success(self, service: str) -> None:
        if not service:
            raise ValueError("service 不能为空")
        with self._lock:
            self._states[service] = self._new_state()

    def snapshot(self, service: str) -> dict[str, Any]:
        if not service:
            raise ValueError("service 不能为空")
        with self._lock:
            return dict(self._state_for(service))

    def _state_for(self, service: str) -> dict[str, Any]:
        return self._states.setdefault(service, self._new_state())

    @staticmethod
    def _new_state() -> dict[str, Any]:
        return {
            "state": "closed",
            "failure_count": 0,
            "opened_at": 0.0,
            "probe_in_flight": False,
        }


class SafetyGuard:
    """按限流、预演、爆炸半径、熔断顺序评估自动修复。"""

    def __init__(
        self,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        max_blast_radius: float = 0.2,
    ) -> None:
        if not isinstance(max_blast_radius, (int, float)) or not 0 <= max_blast_radius <= 1:
            raise ValueError("max_blast_radius 必须在 0 到 1 之间")
        self.rate_limiter = rate_limiter or SlidingWindowRateLimiter()
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.max_blast_radius = float(max_blast_radius)

    def evaluate(self, service: str, proposal: dict[str, Any]) -> dict[str, Any]:
        if not service or not isinstance(proposal, dict):
            raise ValueError("service 不能为空，proposal 必须是对象")
        blast_radius = float(proposal.get("blast_radius", 1.0))
        checks = {
            "rate_limit": self.rate_limiter.allow(service),
            "dry_run": proposal.get("dry_run") is True,
            "blast_radius": 0 <= blast_radius <= self.max_blast_radius,
            "circuit_breaker": None,
        }
        earlier_checks_passed = all(
            checks[name] for name in ("rate_limit", "dry_run", "blast_radius")
        )
        if earlier_checks_passed:
            checks["circuit_breaker"] = self.circuit_breaker.allow(service)
        allowed = all(value is True for value in checks.values())
        failed_check = next((name for name, value in checks.items() if value is False), None)
        return {
            "allowed": allowed,
            "failed_check": failed_check,
            "checks": checks,
            "max_blast_radius": self.max_blast_radius,
            "circuit_state": self.circuit_breaker.snapshot(service)["state"],
        }

    def record_failure(self, service: str) -> None:
        self.circuit_breaker.record_failure(service)

    def record_success(self, service: str) -> None:
        self.circuit_breaker.record_success(service)


class HealAgent:
    def __init__(self, safety_guard: SafetyGuard | None = None, fleet_size: int = 20) -> None:
        if not isinstance(fleet_size, int) or isinstance(fleet_size, bool) or fleet_size < 1:
            raise ValueError("fleet_size 必须是正整数")
        self.safety_guard = safety_guard or SafetyGuard()
        self.fleet_size = fleet_size

    def propose(self, rca: dict[str, Any]) -> dict[str, Any]:
        confidence = float(rca.get("confidence", 0))
        action = "rollback" if confidence >= 0.7 else "restart"
        proposal = {
            "action": action,
            "level": "L1" if confidence >= 0.7 else "L2",
            "dry_run": True,
            "blast_radius": min(1.0, len(rca.get("impact_chain", [])) / self.fleet_size),
        }
        service = str(rca.get("service") or "unknown-service")
        proposal["safety_guard"] = self.safety_guard.evaluate(service, proposal)
        return proposal


class ChangeAgent:
    def approve(self, proposal: dict[str, Any]) -> dict[str, Any]:
        risk = round(float(proposal.get("blast_radius", 1.0)) + (0.15 if proposal.get("action") == "rollback" else 0.25), 3)
        guard_allowed = bool(proposal.get("safety_guard", {}).get("allowed", True))
        approved = bool(proposal.get("dry_run")) and guard_allowed and risk < 0.8
        return {
            "approved": approved,
            "risk": risk,
            "guard_allowed": guard_allowed,
            "auditor": "local-policy",
            "audit_id": uuid.uuid4().hex,
        }


class AIOpsOrchestrator:
    def __init__(
        self,
        store: TaskStore | None = None,
        topology: dict[str, list[str]] | None = None,
        max_retries: int = 2,
        event_bus: EventBus | None = None,
        llm_client: LLMClient | None = None,
        safety_guard: SafetyGuard | None = None,
    ) -> None:
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or not 0 <= max_retries <= 5:
            raise ValueError("max_retries 必须是 0 到 5 的整数")
        self.store = store or TaskStore()
        self.monitor = MonitorAgent()
        self.rca = RcaAgent(topology or {
            "order-service": ["payment-service", "inventory-service"],
            "payment-service": ["mysql"],
        }, llm_client=llm_client)
        self.heal = HealAgent(safety_guard=safety_guard)
        self.change = ChangeAgent()
        self.max_retries = max_retries
        self.event_bus = event_bus or InMemoryEventBus()
        self._approval_lock = threading.RLock()

    def handle(self, alert: Alert) -> TaskRecord:
        self._validate_alert(alert)
        task_id = uuid.uuid4().hex
        state: dict[str, Any] = {"alert": alert.__dict__, "events": []}
        record = TaskRecord(task_id, "aiops", "running", state, utc_now())
        self.store.save(record)
        try:
            monitor_result = self._run_stage(
                "monitor", lambda: self.monitor.confirm(alert), state, record
            )
            if not monitor_result["confirmed"]:
                return self._finish(record, "ignored", state)
            rca_result = self._run_stage(
                "rca", lambda: self.rca.analyze(alert.service, monitor_result), state, record
            )
            proposal = self._run_stage(
                "heal", lambda: self.heal.propose(rca_result), state, record
            )
            approval = self._run_stage(
                "change", lambda: self.change.approve(proposal), state, record
            )
            state["result"] = {"resolved": approval["approved"], "action": proposal["action"], "approval": approval}
            return self._finish(record, "resolved" if approval["approved"] else "awaiting_approval", state)
        except Exception as exc:
            state["error"] = str(exc)
            return self._finish(record, "failed", state)

    def resume_approval(
        self,
        task_id: str,
        approved: bool,
        actor: dict[str, str] | None = None,
    ) -> TaskRecord:
        """恢复等待审批的任务，不重复执行前面的 Agent。"""
        if not task_id or not isinstance(approved, bool):
            raise ValueError("task_id 不能为空，approved 必须是布尔值")
        actor_info = (
            actor
            if actor is not None
            else {"source": "manual", "role": "manual", "id": "local"}
        )
        if not isinstance(actor_info, dict) or any(
            not isinstance(actor_info.get(field), str)
            or not actor_info[field].strip()
            or len(actor_info[field]) > 64
            for field in ("source", "role", "id")
        ):
            raise ValueError("actor 必须包含有效的 source、role 和 id")
        safe_actor = {
            field: actor_info[field].strip()
            for field in ("source", "role", "id")
        }
        with self._approval_lock:
            record = self.store.get(task_id)
            if record is None:
                raise ValueError("任务不存在")
            if record.status != "awaiting_approval":
                raise ValueError("任务当前不在等待审批状态")
            state = record.state
            state.setdefault("events", []).append({
                "stage": "approval_resume",
                "result": {"approved": approved, "actor": safe_actor},
            })
            state.setdefault("result", {})["resolved"] = approved
            finished = TaskRecord(
                record.task_id,
                record.task_type,
                "resolved" if approved else "rejected",
                state,
                utc_now(),
            )
            if not self.store.save_if_status(finished, "awaiting_approval"):
                raise ValueError("任务已被其他实例处理或状态已变化")
            return finished

    def _run_stage(self, name: str, action: Any, state: dict[str, Any], record: TaskRecord) -> Any:
        """阶段级重试：失败记录原因，成功后保存检查点。"""
        for attempt in range(1, self.max_retries + 2):
            try:
                result = action()
                state["events"].append({"stage": name, "attempt": attempt, "result": result})
                self._publish_event("aiops.events", {
                    "task_id": record.task_id,
                    "stage": name,
                    "attempt": attempt,
                    "result": result,
                }, state)
                self._checkpoint(record, state)
                return result
            except Exception as exc:
                state["events"].append({
                    "stage": name,
                    "attempt": attempt,
                    "error": str(exc),
                })
                self._publish_event("aiops.events", {
                    "task_id": record.task_id,
                    "stage": name,
                    "attempt": attempt,
                    "error": str(exc),
                }, state)
                if attempt > self.max_retries:
                    raise RuntimeError(f"{name} 阶段重试耗尽: {exc}") from exc

    @staticmethod
    def _validate_alert(alert: Alert) -> None:
        if not isinstance(alert, Alert) or not alert.service or not alert.metric:
            raise ValueError("alert 必须包含 service 和 metric")
        if not isinstance(alert.baseline, list) or any(
            not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item)
            for item in alert.baseline
        ):
            raise ValueError("baseline 必须是有限数字列表")
        if not isinstance(alert.value, (int, float)) or isinstance(alert.value, bool) or not math.isfinite(alert.value):
            raise ValueError("value 必须是有限数字")

    def _checkpoint(self, record: TaskRecord, state: dict[str, Any]) -> None:
        self.store.save(TaskRecord(record.task_id, record.task_type, "running", state, utc_now()))

    def _publish_event(self, topic: str, payload: dict[str, Any], state: dict[str, Any]) -> None:
        """事件总线故障不阻断主流程，但会留下可追踪记录。"""
        try:
            self.event_bus.publish(topic, payload)
        except Exception as exc:
            state.setdefault("event_bus_errors", []).append({
                "topic": topic,
                "error": str(exc),
            })

    def close(self) -> None:
        self.event_bus.close()
        self.store.close()
        if hasattr(self.rca.topology, "close"):
            self.rca.topology.close()

    def _finish(self, record: TaskRecord, status: str, state: dict[str, Any]) -> TaskRecord:
        finished = TaskRecord(record.task_id, record.task_type, status, state, utc_now())
        self.store.save(finished)
        return finished
