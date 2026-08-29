"""可插拔修复执行器。

默认使用 dry-run；真实执行必须显式选择 allowlist 并提供动作命令配置。
命令始终以参数列表、shell=False 方式执行，避免把服务名拼接进 shell。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence


ALLOWED_ACTIONS = frozenset({"restart", "rollback"})
SERVICE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class RepairExecutor(Protocol):
    def execute(self, service: str, proposal: Mapping[str, Any], task_id: str) -> dict[str, Any]:
        """执行一次修复并返回可审计结果。"""

    def health_check(self, timeout: float = 2.0) -> None:
        """检查执行器配置，不执行修复动作。"""

    def close(self) -> None:
        """释放执行器资源。"""


@dataclass
class DryRunRepairExecutor:
    """只记录意图、不调用操作系统命令的默认执行器。"""

    def execute(self, service: str, proposal: Mapping[str, Any], task_id: str) -> dict[str, Any]:
        _validate_inputs(service, proposal, task_id)
        action = _validate_action(proposal.get("action"))
        return {
            "success": True,
            "executed": False,
            "mode": "dry-run",
            "action": action,
            "service": service,
            "task_id": task_id,
            "message": "dry-run：未调用系统命令",
        }

    def health_check(self, timeout: float = 2.0) -> None:
        _validate_timeout(timeout)

    def close(self) -> None:
        return


class AllowlistRepairExecutor:
    """只执行预先配置的 restart/rollback 命令。

    commands 的格式为 {"restart": ["docker", "restart", "{service}"]}。
    """

    def __init__(
        self,
        commands: Mapping[str, Sequence[str]],
        timeout: float = 30.0,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        if not isinstance(commands, Mapping):
            raise ValueError("commands 必须是对象")
        _validate_timeout(timeout)
        normalized: dict[str, tuple[str, ...]] = {}
        for action, command in commands.items():
            if action not in ALLOWED_ACTIONS:
                raise ValueError(f"不支持的修复动作: {action}")
            if not isinstance(command, Sequence) or isinstance(command, (str, bytes)) or not command:
                raise ValueError(f"{action} 命令必须是非空参数列表")
            if any(not isinstance(item, str) or not item.strip() for item in command):
                raise ValueError(f"{action} 命令参数必须是非空字符串")
            normalized[action] = tuple(item.strip() for item in command)
        self.commands = normalized
        self.timeout = float(timeout)
        self._runner = runner or subprocess.run

    def execute(self, service: str, proposal: Mapping[str, Any], task_id: str) -> dict[str, Any]:
        _validate_inputs(service, proposal, task_id)
        action = _validate_action(proposal.get("action"))
        template = self.commands.get(action)
        if template is None:
            raise ValueError(f"动作未配置白名单命令: {action}")
        command = tuple(item.replace("{service}", service) for item in template)
        completed = self._runner(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            shell=False,
        )
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        result: dict[str, Any] = {
            "success": completed.returncode == 0,
            "executed": True,
            "mode": "allowlist",
            "action": action,
            "service": service,
            "task_id": task_id,
            "returncode": completed.returncode,
            "command": list(command),
        }
        if stdout:
            result["stdout"] = stdout[-2000:]
        if stderr:
            result["stderr"] = stderr[-2000:]
        if completed.returncode != 0:
            raise RuntimeError(f"修复命令执行失败，退出码 {completed.returncode}: {stderr[-500:]}")
        return result

    def health_check(self, timeout: float = 2.0) -> None:
        _validate_timeout(timeout)
        if not self.commands:
            raise RuntimeError("未配置任何修复命令")

    def close(self) -> None:
        return


def _validate_inputs(service: str, proposal: Mapping[str, Any], task_id: str) -> None:
    if not isinstance(service, str) or not SERVICE_PATTERN.fullmatch(service.strip()):
        raise ValueError("service 只能包含字母、数字、下划线、点、冒号或短横线")
    if not isinstance(proposal, Mapping):
        raise ValueError("proposal 必须是对象")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id 不能为空")


def _validate_action(action: Any) -> str:
    if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
        raise ValueError("action 只能是 restart 或 rollback")
    return action


def _validate_timeout(timeout: float) -> None:
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 300:
        raise ValueError("timeout 必须在 0 到 300 秒之间")
