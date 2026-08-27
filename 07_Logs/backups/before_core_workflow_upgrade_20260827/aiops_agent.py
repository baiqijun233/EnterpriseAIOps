"""Enterprise-style AIOps orchestration core with local deterministic inputs."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any

from common.storage import TaskRecord, TaskStore, utc_now


@dataclass
class Alert:
    service: str
    metric: str
    value: float
    baseline: list[float]
    severity: str = "high"


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
    def __init__(self, topology: dict[str, list[str]] | None = None) -> None:
        self.topology = topology or {}

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
            queue.extend(self.topology.get(current, []))
        related = sorted(visited)
        confidence = 0.72 if len(related) > 1 else 0.48
        return {"root_cause": f"{service} 近期指标异常", "confidence": confidence, "impact_chain": related, "evidence": alert}


class HealAgent:
    def propose(self, rca: dict[str, Any]) -> dict[str, Any]:
        confidence = float(rca.get("confidence", 0))
        action = "rollback" if confidence >= 0.7 else "restart"
        return {"action": action, "level": "L1" if confidence >= 0.7 else "L2", "dry_run": True, "blast_radius": min(1.0, len(rca.get("impact_chain", [])) / 10)}


class ChangeAgent:
    def approve(self, proposal: dict[str, Any]) -> dict[str, Any]:
        risk = round(float(proposal.get("blast_radius", 1.0)) + (0.15 if proposal.get("action") == "rollback" else 0.25), 3)
        approved = bool(proposal.get("dry_run")) and risk < 0.8
        return {"approved": approved, "risk": risk, "auditor": "local-policy", "audit_id": uuid.uuid4().hex}


class AIOpsOrchestrator:
    def __init__(self, store: TaskStore | None = None) -> None:
        self.store = store or TaskStore()
        self.monitor = MonitorAgent()
        self.rca = RcaAgent({"order-service": ["payment-service", "inventory-service"], "payment-service": ["mysql"]})
        self.heal = HealAgent()
        self.change = ChangeAgent()

    def handle(self, alert: Alert) -> TaskRecord:
        if not isinstance(alert, Alert) or not alert.service or not alert.metric:
            raise ValueError("alert 必须包含 service 和 metric")
        task_id = uuid.uuid4().hex
        state: dict[str, Any] = {"alert": alert.__dict__, "events": []}
        record = TaskRecord(task_id, "aiops", "running", state, utc_now())
        self.store.save(record)
        try:
            monitor_result = self.monitor.confirm(alert)
            state["events"].append({"stage": "monitor", "result": monitor_result})
            if not monitor_result["confirmed"]:
                return self._finish(record, "ignored", state)
            rca_result = self.rca.analyze(alert.service, monitor_result)
            state["events"].append({"stage": "rca", "result": rca_result})
            proposal = self.heal.propose(rca_result)
            state["events"].append({"stage": "heal", "result": proposal})
            approval = self.change.approve(proposal)
            state["events"].append({"stage": "change", "result": approval})
            state["result"] = {"resolved": approval["approved"], "action": proposal["action"], "approval": approval}
            return self._finish(record, "resolved" if approval["approved"] else "awaiting_approval", state)
        except Exception as exc:
            state["error"] = str(exc)
            return self._finish(record, "failed", state)

    def _finish(self, record: TaskRecord, status: str, state: dict[str, Any]) -> TaskRecord:
        finished = TaskRecord(record.task_id, record.task_type, status, state, utc_now())
        self.store.save(finished)
        return finished
