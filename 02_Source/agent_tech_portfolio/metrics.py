"""无第三方依赖的 Prometheus 文本指标注册器。"""

from __future__ import annotations

import threading


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._lock = threading.RLock()

    def increment(self, name: str, amount: int = 1) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("指标名称不能为空")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
            raise ValueError("amount 必须是正整数")
        with self._lock:
            self._counters[name.strip()] = self._counters.get(name.strip(), 0) + amount

    def render(self) -> str:
        with self._lock:
            rows = [f"# TYPE {name} counter\n{name} {value}" for name, value in sorted(self._counters.items())]
        return "\n".join(rows) + ("\n" if rows else "")
