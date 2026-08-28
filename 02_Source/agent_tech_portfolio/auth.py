"""API Key 认证与角色权限控制，不依赖第三方库。"""

from __future__ import annotations

import hmac
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Mapping


class AuthenticationError(ValueError):
    """请求未提供有效身份凭证。"""


class AuthorizationError(PermissionError):
    """已认证的身份没有目标操作权限。"""


@dataclass(frozen=True)
class AuthPrincipal:
    role: str
    key_id: str
    auth_enabled: bool


class AuthManager:
    """从环境变量加载 API Key，并按角色等级授权。"""

    ROLE_LEVELS = {
        "viewer": 10,
        "operator": 20,
        "approver": 30,
        "admin": 40,
    }
    TRUE_VALUES = {"1", "true", "yes", "on"}
    FALSE_VALUES = {"", "0", "false", "no", "off"}

    def __init__(
        self,
        api_keys: Mapping[str, str] | None = None,
        enabled: bool = False,
    ) -> None:
        if not isinstance(enabled, bool):
            raise ValueError("enabled 必须是布尔值")
        key_mapping = dict(api_keys or {})
        if enabled and not key_mapping:
            raise ValueError("启用认证时必须配置至少一个 API Key")
        if len(key_mapping) > 100:
            raise ValueError("API Key 数量不能超过 100")

        validated_keys: list[tuple[str, str, str]] = []
        for api_key, role in key_mapping.items():
            if not isinstance(api_key, str) or len(api_key.strip()) < 16:
                raise ValueError("API Key 必须是至少 16 位的字符串")
            if not isinstance(role, str) or role.strip().lower() not in self.ROLE_LEVELS:
                raise ValueError("API Key 角色只能是 viewer、operator、approver 或 admin")
            normalized_key = api_key.strip()
            key_id = hashlib.sha256(normalized_key.encode("utf-8")).hexdigest()[:12]
            validated_keys.append((normalized_key, role.strip().lower(), key_id))

        self.enabled = enabled
        self._api_keys = tuple(validated_keys)

    @classmethod
    def from_environment(cls) -> "AuthManager":
        raw_enabled = os.getenv("AIOPS_AUTH_ENABLED", "false").strip().lower()
        if raw_enabled in cls.TRUE_VALUES:
            enabled = True
        elif raw_enabled in cls.FALSE_VALUES:
            enabled = False
        else:
            raise ValueError("AIOPS_AUTH_ENABLED 只能是 true 或 false")
        if not enabled:
            return cls(enabled=False)

        raw_keys = os.getenv("AIOPS_API_KEYS", "").strip()
        try:
            key_mapping = json.loads(raw_keys)
        except json.JSONDecodeError as exc:
            raise ValueError("AIOPS_API_KEYS 必须是 JSON 对象") from exc
        if not isinstance(key_mapping, dict):
            raise ValueError("AIOPS_API_KEYS 必须是 JSON 对象")
        return cls(key_mapping, enabled=True)

    def authorize(self, api_key: str | None, required_role: str) -> AuthPrincipal:
        normalized_role = str(required_role).strip().lower()
        if normalized_role not in self.ROLE_LEVELS:
            raise ValueError("未知的权限角色")
        if not self.enabled:
            return AuthPrincipal(role="admin", key_id="local", auth_enabled=False)
        if not isinstance(api_key, str) or not api_key.strip():
            raise AuthenticationError("缺少或无效的 API Key")

        supplied_key = api_key.strip()
        matched_role: str | None = None
        matched_key_id: str | None = None
        for configured_key, configured_role, key_id in self._api_keys:
            if hmac.compare_digest(supplied_key, configured_key):
                matched_role = configured_role
                matched_key_id = key_id
        if matched_role is None:
            raise AuthenticationError("缺少或无效的 API Key")
        if self.ROLE_LEVELS[matched_role] < self.ROLE_LEVELS[normalized_role]:
            raise AuthorizationError("当前 API Key 权限不足")
        return AuthPrincipal(
            role=matched_role,
            key_id=str(matched_key_id),
            auth_enabled=True,
        )
