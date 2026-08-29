"""Redis 共享安全状态：多实例原子限流与熔断。"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Callable

from aiops_agent import SafetyGuard


def _service_key(prefix: str, service: str) -> str:
    if not isinstance(service, str) or not service.strip():
        raise ValueError("service 不能为空")
    digest = hashlib.sha256(service.strip().encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


class RedisSlidingWindowRateLimiter:
    SCRIPT = """
-- AIOPS_RATE_LIMIT
local server_time = redis.call('TIME')
local now = tonumber(server_time[1]) + tonumber(server_time[2]) / 1000000
local window_seconds = tonumber(ARGV[1])
local max_actions = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window_seconds)
local current_count = redis.call('ZCARD', KEYS[1])
if current_count >= max_actions then
    return 0
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], math.ceil(window_seconds * 1000))
return 1
"""

    def __init__(
        self,
        client: Any,
        max_actions: int = 5,
        window_seconds: float = 60.0,
        key_prefix: str = "aiops:safety:rate",
    ) -> None:
        if client is None:
            raise ValueError("client 不能为空")
        if not isinstance(max_actions, int) or isinstance(max_actions, bool) or max_actions < 1:
            raise ValueError("max_actions 必须是正整数")
        if (
            not isinstance(window_seconds, (int, float))
            or isinstance(window_seconds, bool)
            or window_seconds <= 0
        ):
            raise ValueError("window_seconds 必须大于 0")
        if not isinstance(key_prefix, str) or not key_prefix.strip():
            raise ValueError("key_prefix 不能为空")
        self.client = client
        self.max_actions = max_actions
        self.window_seconds = float(window_seconds)
        self.key_prefix = key_prefix.strip().rstrip(":")

    def allow(self, service: str) -> bool:
        result = self.client.eval(
            self.SCRIPT,
            1,
            _service_key(self.key_prefix, service),
            self.window_seconds,
            self.max_actions,
            uuid.uuid4().hex,
        )
        return int(result) == 1


class RedisCircuitBreaker:
    ALLOW_SCRIPT = """
-- AIOPS_CIRCUIT_ALLOW
local recovery_seconds = tonumber(ARGV[1])
local state = redis.call('HGET', KEYS[1], 'state') or 'closed'
local failure_count = tonumber(redis.call('HGET', KEYS[1], 'failure_count') or '0')
if state == 'closed' then
    return {1, 'closed', failure_count}
end
if state == 'half_open' then
    return {0, 'half_open', failure_count}
end
local server_time = redis.call('TIME')
local now = tonumber(server_time[1]) + tonumber(server_time[2]) / 1000000
local opened_at = tonumber(redis.call('HGET', KEYS[1], 'opened_at') or '0')
if now - opened_at < recovery_seconds then
    return {0, 'open', failure_count}
end
redis.call('HSET', KEYS[1], 'state', 'half_open', 'probe_in_flight', '1')
redis.call('PEXPIRE', KEYS[1], math.ceil(math.max(300, recovery_seconds * 10) * 1000))
return {1, 'half_open', failure_count}
"""

    FAILURE_SCRIPT = """
-- AIOPS_CIRCUIT_FAILURE
local failure_threshold = tonumber(ARGV[1])
local recovery_seconds = tonumber(ARGV[2])
local state = redis.call('HGET', KEYS[1], 'state') or 'closed'
local failure_count = redis.call('HINCRBY', KEYS[1], 'failure_count', 1)
if state == 'half_open' or failure_count >= failure_threshold then
    local server_time = redis.call('TIME')
    local now = tonumber(server_time[1]) + tonumber(server_time[2]) / 1000000
    redis.call('HSET', KEYS[1], 'state', 'open', 'opened_at', now, 'probe_in_flight', '0')
    state = 'open'
else
    redis.call('HSET', KEYS[1], 'state', 'closed', 'probe_in_flight', '0')
    state = 'closed'
end
redis.call('PEXPIRE', KEYS[1], math.ceil(math.max(300, recovery_seconds * 10) * 1000))
return {state, failure_count}
"""

    def __init__(
        self,
        client: Any,
        failure_threshold: int = 3,
        recovery_seconds: float = 60.0,
        key_prefix: str = "aiops:safety:circuit",
    ) -> None:
        if client is None:
            raise ValueError("client 不能为空")
        if (
            not isinstance(failure_threshold, int)
            or isinstance(failure_threshold, bool)
            or failure_threshold < 1
        ):
            raise ValueError("failure_threshold 必须是正整数")
        if (
            not isinstance(recovery_seconds, (int, float))
            or isinstance(recovery_seconds, bool)
            or recovery_seconds <= 0
        ):
            raise ValueError("recovery_seconds 必须大于 0")
        if not isinstance(key_prefix, str) or not key_prefix.strip():
            raise ValueError("key_prefix 不能为空")
        self.client = client
        self.failure_threshold = failure_threshold
        self.recovery_seconds = float(recovery_seconds)
        self.key_prefix = key_prefix.strip().rstrip(":")

    def allow(self, service: str) -> bool:
        result = self.client.eval(
            self.ALLOW_SCRIPT,
            1,
            self._key(service),
            self.recovery_seconds,
        )
        return int(result[0]) == 1

    def record_failure(self, service: str) -> None:
        self.client.eval(
            self.FAILURE_SCRIPT,
            1,
            self._key(service),
            self.failure_threshold,
            self.recovery_seconds,
        )

    def record_success(self, service: str) -> None:
        self.client.delete(self._key(service))

    def snapshot(self, service: str) -> dict[str, Any]:
        raw_state = self.client.hgetall(self._key(service)) or {}
        state = {_text(key): _text(value) for key, value in raw_state.items()}
        return {
            "state": state.get("state", "closed"),
            "failure_count": int(state.get("failure_count", 0)),
            "opened_at": float(state.get("opened_at", 0.0)),
            "probe_in_flight": state.get("probe_in_flight", "0") == "1",
        }

    def _key(self, service: str) -> str:
        return _service_key(self.key_prefix, service)


class RedisSafetyGuard(SafetyGuard):
    """保持 SafetyGuard 接口不变，将共享状态存入 Redis。"""

    def __init__(
        self,
        url: str,
        max_actions: int = 5,
        window_seconds: float = 60.0,
        failure_threshold: int = 3,
        recovery_seconds: float = 60.0,
        max_blast_radius: float = 0.2,
        key_prefix: str = "project024:aiops:safety",
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        if not isinstance(url, str) or not url.startswith(("redis://", "rediss://")):
            raise ValueError("url 必须是 redis:// 或 rediss:// 地址")
        if client_factory is not None and not callable(client_factory):
            raise ValueError("client_factory 必须可调用")
        if client_factory is not None:
            client = client_factory(url)
        else:
            try:
                import redis
            except ImportError as exc:
                raise RuntimeError(
                    "Redis 安全后端需要安装 redis：python -m pip install redis"
                ) from exc
            client = redis.Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        self.url = url
        self._client = client
        self._closed = False
        normalized_prefix = key_prefix.strip().rstrip(":") if isinstance(key_prefix, str) else ""
        if not normalized_prefix:
            raise ValueError("key_prefix 不能为空")
        super().__init__(
            rate_limiter=RedisSlidingWindowRateLimiter(
                client,
                max_actions=max_actions,
                window_seconds=window_seconds,
                key_prefix=f"{normalized_prefix}:rate",
            ),
            circuit_breaker=RedisCircuitBreaker(
                client,
                failure_threshold=failure_threshold,
                recovery_seconds=recovery_seconds,
                key_prefix=f"{normalized_prefix}:circuit",
            ),
            max_blast_radius=max_blast_radius,
        )

    def health_check(self, timeout: float = 2.0) -> None:
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("timeout 必须是正数")
        if self._client.ping() is not True:
            raise RuntimeError("Redis PING 未返回成功")

    def close(self) -> None:
        if not self._closed and hasattr(self._client, "close"):
            self._client.close()
        self._closed = True
