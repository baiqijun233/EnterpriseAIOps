"""Agent 事件总线：内存实现和可选 Kafka 实现。"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Protocol


class EventBus(Protocol):
    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """发布一个可 JSON 序列化的事件。"""

    def close(self) -> None:
        """释放底层连接。"""


class InMemoryEventBus:
    """本地开发和测试使用的事件总线。"""

    def __init__(self, max_events: int = 1000) -> None:
        if not isinstance(max_events, int) or isinstance(max_events, bool) or max_events < 1:
            raise ValueError("max_events 必须是正整数")
        self._max_events = max_events
        self._events: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        _validate_event(topic, payload)
        event = {
            "topic": topic,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._events.append(event)
            del self._events[:-self._max_events]

    def get_events(self, topic: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._events)
        if topic is None:
            return events
        return [event for event in events if event["topic"] == topic]

    def close(self) -> None:
        return


class KafkaEventBus:
    """Kafka 适配器，只有显式使用时才要求安装 confluent-kafka。"""

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        max_retries: int = 3,
        producer_factory: Callable[[dict[str, Any]], Any] | None = None,
        consumer_factory: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        if not bootstrap_servers or not isinstance(bootstrap_servers, str):
            raise ValueError("bootstrap_servers 必须是非空字符串")
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or not 0 <= max_retries <= 10:
            raise ValueError("max_retries 必须是 0 到 10 的整数")
        self.bootstrap_servers = bootstrap_servers
        self.max_retries = max_retries
        self._producer_factory = producer_factory
        self._consumer_factory = consumer_factory
        self._producer: Any | None = None

    def _get_producer(self) -> Any:
        if self._producer is not None:
            return self._producer
        if self._producer_factory is not None:
            self._producer = self._producer_factory({
                "bootstrap.servers": self.bootstrap_servers,
                "acks": "all",
                "retries": self.max_retries,
            })
            return self._producer
        try:
            from confluent_kafka import Producer
        except ImportError as exc:
            raise RuntimeError(
                "Kafka 模式需要安装 confluent-kafka：python -m pip install confluent-kafka"
            ) from exc
        self._producer = Producer({
            "bootstrap.servers": self.bootstrap_servers,
            "acks": "all",
            "retries": self.max_retries,
            "retry.backoff.ms": 100,
        })
        return self._producer

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        _validate_event(topic, payload)
        message = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        producer = self._get_producer()
        last_error: Exception | None = None
        for _ in range(self.max_retries + 1):
            try:
                producer.produce(topic=topic, value=message)
                remaining = producer.flush(timeout=5)
                if remaining:
                    raise TimeoutError(f"Kafka 仍有 {remaining} 条消息未发送")
                return
            except Exception as exc:  # Kafka 客户端异常类型需保持可选依赖
                last_error = exc
        raise RuntimeError(f"Kafka 事件发布失败: {last_error}") from last_error

    def consume_once(
        self,
        topic: str,
        group_id: str,
        handler: Callable[[dict[str, Any]], Any],
        timeout: float = 1.0,
    ) -> bool:
        """消费一条消息；处理失败时写入 `<topic>.dlq` 并确认原消息。"""
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError("group_id 不能为空")
        if not callable(handler):
            raise ValueError("handler 必须可调用")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("timeout 必须是正数")
        consumer = self._create_consumer(group_id)
        consumer.subscribe([topic])
        try:
            message = consumer.poll(timeout=float(timeout))
            if message is None:
                return False
            if message.error():
                raise RuntimeError(f"Kafka 消费失败: {message.error()}")
            raw_value = message.value()
            try:
                payload = json.loads(raw_value.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("消息 payload 必须是对象")
                handler(payload)
            except Exception as exc:
                self._publish_dead_letter(topic, raw_value, str(exc))
            consumer.commit(asynchronous=False)
            return True
        finally:
            consumer.close()

    def _create_consumer(self, group_id: str) -> Any:
        config = {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "latest",
            "enable.auto.commit": False,
        }
        if self._consumer_factory is not None:
            return self._consumer_factory(config)
        try:
            from confluent_kafka import Consumer
        except ImportError as exc:
            raise RuntimeError(
                "Kafka 模式需要安装 confluent-kafka：python -m pip install confluent-kafka"
            ) from exc
        return Consumer(config)

    def _publish_dead_letter(self, topic: str, raw_value: bytes, error: str) -> None:
        producer = self._get_producer()
        payload = {
            "original_topic": topic,
            "error": error,
            "raw_value": raw_value.decode("utf-8", errors="replace"),
        }
        producer.produce(
            topic=f"{topic}.dlq",
            value=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )
        remaining = producer.flush(timeout=5)
        if remaining:
            raise TimeoutError(f"Kafka DLQ 仍有 {remaining} 条消息未发送")

    def close(self) -> None:
        if self._producer is not None:
            self._producer.flush(timeout=10)


def create_event_bus(use_kafka: bool = False, **kwargs: Any) -> EventBus:
    if not isinstance(use_kafka, bool):
        raise ValueError("use_kafka 必须是布尔值")
    return KafkaEventBus(**kwargs) if use_kafka else InMemoryEventBus()


def _validate_event(topic: str, payload: dict[str, Any]) -> None:
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("topic 不能为空")
    if not isinstance(payload, dict):
        raise ValueError("事件 payload 必须是对象")
    try:
        json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"事件 payload 不可 JSON 序列化: {exc}") from exc
