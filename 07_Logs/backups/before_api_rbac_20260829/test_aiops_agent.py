import sys
import unittest
import json
import tempfile
from unittest.mock import patch
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "02_Source" / "agent_tech_portfolio"
sys.path.insert(0, str(SOURCE))

from aiops_agent import (
    AIOpsOrchestrator,
    Alert,
    CircuitBreaker,
    RcaAgent,
    SafetyGuard,
    SlidingWindowRateLimiter,
)
from api_server import create_server
from common.storage import TaskStore
from event_bus import InMemoryEventBus, KafkaEventBus
from fastapi_app import create_app
from llm_adapter import DeepSeekLLMClient, DeterministicLLMClient
from adapters.neo4j_topology import Neo4jTopologyProvider
from adapters.task_queue import CeleryTaskDispatcher, RedisTaskQueue
from metrics import MetricsRegistry


class AIOpsAgentTests(unittest.TestCase):
    def test_rate_limiter_recovers_after_window(self):
        current_time = [100.0]
        limiter = SlidingWindowRateLimiter(
            max_actions=2,
            window_seconds=10,
            clock=lambda: current_time[0],
        )
        self.assertTrue(limiter.allow("order-service"))
        self.assertTrue(limiter.allow("order-service"))
        self.assertFalse(limiter.allow("order-service"))
        current_time[0] = 111.0
        self.assertTrue(limiter.allow("order-service"))

    def test_circuit_breaker_opens_and_allows_one_half_open_probe(self):
        current_time = [100.0]
        breaker = CircuitBreaker(
            failure_threshold=2,
            recovery_seconds=10,
            clock=lambda: current_time[0],
        )
        breaker.record_failure("order-service")
        breaker.record_failure("order-service")
        self.assertEqual(breaker.snapshot("order-service")["state"], "open")
        self.assertFalse(breaker.allow("order-service"))
        current_time[0] = 111.0
        self.assertTrue(breaker.allow("order-service"))
        self.assertFalse(breaker.allow("order-service"))
        breaker.record_success("order-service")
        self.assertTrue(breaker.allow("order-service"))

    def test_pipeline_records_complete_safety_guard_chain(self):
        result = AIOpsOrchestrator().handle(
            Alert("order-service", "cpu", 95.0, [40, 41, 39, 42, 40])
        )
        heal_event = next(event for event in result.state["events"] if event["stage"] == "heal")
        guard = heal_event["result"]["safety_guard"]
        self.assertEqual(result.status, "resolved")
        self.assertTrue(guard["allowed"])
        self.assertEqual(
            list(guard["checks"]),
            ["rate_limit", "dry_run", "blast_radius", "circuit_breaker"],
        )

    def test_open_circuit_breaker_requires_manual_approval(self):
        guard = SafetyGuard(circuit_breaker=CircuitBreaker(failure_threshold=1))
        guard.record_failure("order-service")
        orchestrator = AIOpsOrchestrator(safety_guard=guard)
        result = orchestrator.handle(
            Alert("order-service", "cpu", 95.0, [40, 41, 39, 42, 40])
        )
        heal_event = next(event for event in result.state["events"] if event["stage"] == "heal")
        self.assertEqual(result.status, "awaiting_approval")
        self.assertEqual(
            heal_event["result"]["safety_guard"]["failed_check"],
            "circuit_breaker",
        )
        orchestrator.close()

    def test_rate_limit_requires_manual_approval_after_threshold(self):
        guard = SafetyGuard(
            rate_limiter=SlidingWindowRateLimiter(max_actions=1, window_seconds=60)
        )
        orchestrator = AIOpsOrchestrator(safety_guard=guard)
        first = orchestrator.handle(
            Alert("order-service", "cpu", 95.0, [40, 41, 39, 42, 40])
        )
        second = orchestrator.handle(
            Alert("order-service", "cpu", 96.0, [40, 41, 39, 42, 40])
        )
        heal_event = next(event for event in second.state["events"] if event["stage"] == "heal")
        self.assertEqual(first.status, "resolved")
        self.assertEqual(second.status, "awaiting_approval")
        self.assertEqual(
            heal_event["result"]["safety_guard"]["failed_check"],
            "rate_limit",
        )
        orchestrator.close()

    def test_anomaly_pipeline_records_audit(self):
        result = AIOpsOrchestrator().handle(Alert("order-service", "cpu", 95.0, [40, 41, 39, 42, 40]))
        self.assertIn(result.status, {"resolved", "awaiting_approval"})
        self.assertTrue(result.state["events"])
        self.assertIn("audit_id", result.state["events"][-1]["result"])

    def test_normal_metric_is_ignored(self):
        result = AIOpsOrchestrator().handle(Alert("order-service", "cpu", 41.0, [40, 41, 39, 42, 40]))
        self.assertEqual(result.status, "ignored")

    def test_task_store_lists_recent_tasks_with_limit(self):
        orchestrator = AIOpsOrchestrator()
        orchestrator.handle(Alert("order-service", "cpu", 95.0, [40, 41, 39, 42, 40]))
        orchestrator.handle(Alert("order-service", "cpu", 41.0, [40, 41, 39, 42, 40]))
        self.assertEqual(len(orchestrator.store.list_recent(1)), 1)
        self.assertLessEqual(len(orchestrator.store.list_recent(0)), 1)

    def test_failed_stage_retries_and_saves_attempts(self):
        orchestrator = AIOpsOrchestrator(max_retries=1)
        original_confirm = orchestrator.monitor.confirm
        calls = {"count": 0}

        def flaky_confirm(alert):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("模拟监控暂时不可用")
            return original_confirm(alert)

        orchestrator.monitor.confirm = flaky_confirm
        result = orchestrator.handle(Alert("order-service", "cpu", 95.0, [40, 41, 39, 42, 40]))
        monitor_events = [event for event in result.state["events"] if event["stage"] == "monitor"]
        self.assertEqual(calls["count"], 2)
        self.assertIn("error", monitor_events[0])
        self.assertEqual(monitor_events[-1]["attempt"], 2)

    def test_approval_can_resume_without_rerunning_pipeline(self):
        orchestrator = AIOpsOrchestrator()
        calls = {"count": 0}

        def pending_approval(proposal):
            calls["count"] += 1
            return {"approved": False, "risk": 0.9, "audit_id": "test-audit"}

        orchestrator.change.approve = pending_approval
        pending = orchestrator.handle(Alert("order-service", "cpu", 95.0, [40, 41, 39, 42, 40]))
        self.assertEqual(pending.status, "awaiting_approval")
        resumed = orchestrator.resume_approval(pending.task_id, True)
        self.assertEqual(resumed.status, "resolved")
        self.assertEqual(calls["count"], 1)
        self.assertEqual(resumed.state["events"][-1]["stage"], "approval_resume")

    def test_approval_resume_is_single_use_under_concurrency(self):
        orchestrator = AIOpsOrchestrator()
        orchestrator.change.approve = lambda proposal: {
            "approved": False, "risk": 0.9, "audit_id": "test-audit"
        }
        pending = orchestrator.handle(Alert("order-service", "cpu", 95.0, [40, 41, 39, 42, 40]))
        results = []

        def resume() -> None:
            try:
                results.append(orchestrator.resume_approval(pending.task_id, True).status)
            except ValueError as exc:
                results.append(type(exc).__name__)

        threads = [Thread(target=resume) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(results.count("resolved"), 1)
        self.assertEqual(results.count("ValueError"), 1)
        orchestrator.close()

    def test_sqlite_task_can_be_read_by_new_orchestrator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "tasks.sqlite3"
            first = AIOpsOrchestrator(store=TaskStore(database_path))
            second = AIOpsOrchestrator(store=TaskStore(database_path))
            try:
                created = first.handle(Alert("order-service", "cpu", 95.0, [40, 41, 39, 42, 40]))
                restored = second.store.get(created.task_id)
                self.assertIsNotNone(restored)
                self.assertEqual(restored.status, created.status)
            finally:
                first.store.close()
                second.store.close()

    def test_approval_resume_is_single_use_across_two_stores(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "tasks.sqlite3"
            first = AIOpsOrchestrator(store=TaskStore(database_path))
            second = AIOpsOrchestrator(store=TaskStore(database_path))
            first.change.approve = lambda proposal: {
                "approved": False,
                "risk": 0.9,
                "audit_id": "test-audit",
            }
            try:
                pending = first.handle(
                    Alert("order-service", "cpu", 95.0, [40, 41, 39, 42, 40])
                )
                results = []

                def resume(orchestrator):
                    try:
                        results.append(
                            orchestrator.resume_approval(pending.task_id, True).status
                        )
                    except ValueError as exc:
                        results.append(type(exc).__name__)

                threads = [Thread(target=resume, args=(item,)) for item in (first, second)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=2)

                self.assertEqual(results.count("resolved"), 1)
                self.assertEqual(results.count("ValueError"), 1)
                self.assertEqual(first.store.get(pending.task_id).status, "resolved")
            finally:
                first.close()
                second.close()

    def test_orchestrator_publishes_stage_events(self):
        event_bus = InMemoryEventBus()
        orchestrator = AIOpsOrchestrator(event_bus=event_bus)
        orchestrator.handle(Alert("order-service", "cpu", 95.0, [40, 41, 39, 42, 40]))
        topics = [event["topic"] for event in event_bus.get_events()]
        self.assertIn("aiops.events", topics)

    def test_kafka_adapter_serializes_event_with_ack_policy(self):
        class FakeProducer:
            def __init__(self):
                self.messages = []
                self.flush_calls = 0

            def produce(self, **kwargs):
                self.messages.append(kwargs)

            def flush(self, timeout):
                self.flush_calls += 1
                return 0

        fake = FakeProducer()
        received_config = {}

        def producer_factory(config):
            received_config.update(config)
            return fake

        bus = KafkaEventBus(producer_factory=producer_factory)
        bus.publish("aiops.events", {"task_id": "t-1", "stage": "monitor"})
        self.assertEqual(received_config["acks"], "all")
        self.assertEqual(fake.messages[0]["topic"], "aiops.events")
        self.assertEqual(json.loads(fake.messages[0]["value"])["task_id"], "t-1")
        self.assertEqual(fake.flush_calls, 1)

    def test_kafka_consumer_sends_failed_message_to_dlq(self):
        class FakeMessage:
            def __init__(self, value):
                self._value = value

            def error(self):
                return None

            def value(self):
                return self._value

        class FakeConsumer:
            def __init__(self):
                self.committed = 0
                self.closed = False

            def subscribe(self, topics):
                self.topics = topics

            def poll(self, timeout):
                return FakeMessage(b"{\"task_id\": \"t-2\"}")

            def commit(self, asynchronous=False):
                self.committed += 1

            def close(self):
                self.closed = True

        class FakeProducer:
            def __init__(self):
                self.messages = []

            def produce(self, **kwargs):
                self.messages.append(kwargs)

            def flush(self, timeout):
                return 0

        consumer = FakeConsumer()
        producer = FakeProducer()
        bus = KafkaEventBus(
            producer_factory=lambda config: producer,
            consumer_factory=lambda config: consumer,
        )
        consumed = bus.consume_once("aiops.events", "rca-agent", lambda payload: (_ for _ in ()).throw(RuntimeError("处理失败")))
        self.assertTrue(consumed)
        self.assertEqual(consumer.committed, 1)
        self.assertTrue(consumer.closed)
        self.assertEqual(producer.messages[0]["topic"], "aiops.events.dlq")

    def test_deterministic_llm_can_explain_rca_without_network(self):
        result = RcaAgent(
            {"order-service": ["mysql"]},
            llm_client=DeterministicLLMClient(),
        ).analyze("order-service", {"metric": "cpu"})
        self.assertIn("explanation", result)
        self.assertNotIn("llm_error", result)

    def test_deepseek_client_uses_openai_compatible_request(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({
                    "choices": [{"message": {"content": "已完成根因解释"}}]
                }).encode("utf-8")

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse()

        with patch("llm_adapter.urlopen", fake_urlopen):
            client = DeepSeekLLMClient("sk-test", model="deepseek-chat")
            content = client.generate("分析故障", {"service": "order-service"})

        self.assertEqual(content, "已完成根因解释")
        self.assertEqual(captured["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(captured["body"]["model"], "deepseek-chat")
        self.assertIn("结构化上下文", captured["body"]["messages"][0]["content"])

    def test_api_auto_mode_prefers_deepseek_when_key_exists(self):
        import os
        from api_server import build_orchestrator

        old_mode = os.environ.get("AIOPS_LLM")
        old_key = os.environ.get("AIOPS_DEEPSEEK_API_KEY")
        try:
            os.environ.pop("AIOPS_LLM", None)
            os.environ["AIOPS_DEEPSEEK_API_KEY"] = "sk-test"
            orchestrator = build_orchestrator()
            self.assertIsInstance(orchestrator.rca.llm_client, DeepSeekLLMClient)
            orchestrator.close()
        finally:
            if old_mode is None:
                os.environ.pop("AIOPS_LLM", None)
            else:
                os.environ["AIOPS_LLM"] = old_mode
            if old_key is None:
                os.environ.pop("AIOPS_DEEPSEEK_API_KEY", None)
            else:
                os.environ["AIOPS_DEEPSEEK_API_KEY"] = old_key

    def test_api_auto_mode_falls_back_without_key(self):
        import os
        from api_server import build_orchestrator

        old_mode = os.environ.get("AIOPS_LLM")
        old_key = os.environ.get("AIOPS_DEEPSEEK_API_KEY")
        try:
            os.environ.pop("AIOPS_LLM", None)
            os.environ.pop("AIOPS_DEEPSEEK_API_KEY", None)
            orchestrator = build_orchestrator()
            self.assertIsNone(orchestrator.rca.llm_client)
            orchestrator.close()
        finally:
            if old_mode is None:
                os.environ.pop("AIOPS_LLM", None)
            else:
                os.environ["AIOPS_LLM"] = old_mode
            if old_key is None:
                os.environ.pop("AIOPS_DEEPSEEK_API_KEY", None)
            else:
                os.environ["AIOPS_DEEPSEEK_API_KEY"] = old_key

    def test_fastapi_entry_runs_real_routes(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("FastAPI 测试依赖未安装")
        orchestrator = AIOpsOrchestrator()
        client = TestClient(create_app(orchestrator))
        self.assertEqual(client.get("/health").status_code, 200)
        response = client.post("/api/v1/incidents", json={
            "service": "order-service",
            "metric": "cpu",
            "value": 95,
            "baseline": [40, 41, 39, 42, 40],
        })
        self.assertEqual(response.status_code, 201)
        task_id = response.json()["task_id"]
        self.assertEqual(client.get(f"/api/v1/tasks/{task_id}").status_code, 200)
        metrics_response = client.get("/metrics")
        self.assertEqual(metrics_response.status_code, 200)
        self.assertIn("aiops_fastapi_requests_total", metrics_response.text)
        orchestrator.close()

    def test_fastapi_metrics_accumulate_for_one_app(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("FastAPI 测试依赖未安装")
        orchestrator = AIOpsOrchestrator()
        client = TestClient(create_app(orchestrator))
        first = client.get("/metrics")
        second = client.get("/metrics")
        self.assertEqual(first.status_code, 200)
        self.assertIn("aiops_fastapi_requests_total 2", second.text)
        orchestrator.close()

    def test_rca_can_use_neo4j_style_topology_provider(self):
        class Provider:
            def get_dependencies(self, service):
                return ["payment-service"] if service == "order-service" else []

        result = RcaAgent(Provider()).analyze("order-service", {})
        self.assertEqual(result["impact_chain"], ["order-service", "payment-service"])

    def test_neo4j_adapter_reads_service_dependencies(self):
        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def run(self, query, service):
                self.query = query
                self.service = service
                return [{"name": "mysql"}]

        class FakeDriver:
            def __init__(self):
                self.session_obj = FakeSession()
                self.closed = False

            def session(self):
                return self.session_obj

            def close(self):
                self.closed = True

        driver = FakeDriver()
        provider = Neo4jTopologyProvider(
            "bolt://localhost:7687",
            "neo4j",
            "password",
            driver_factory=lambda uri, auth: driver,
        )
        self.assertEqual(provider.get_dependencies("payment-service"), ["mysql"])
        provider.close()
        self.assertTrue(driver.closed)

    def test_redis_and_celery_adapters_dispatch_json_tasks(self):
        class FakeRedis:
            def __init__(self):
                self.items = []

            def rpush(self, queue, value):
                self.items.append((queue, value))

            def blpop(self, queue, timeout):
                return self.items.pop(0) if self.items else None

            def close(self):
                return

        redis_client = FakeRedis()
        queue = RedisTaskQueue(client_factory=lambda url: redis_client)
        queue.enqueue("aiops", {"task_id": "t-3"})
        self.assertEqual(queue.dequeue("aiops")["task_id"], "t-3")

        class FakeResult:
            id = "celery-1"

        class FakeCelery:
            def send_task(self, name, kwargs):
                self.name = name
                self.kwargs = kwargs
                return FakeResult()

        dispatcher = CeleryTaskDispatcher(
            "redis://localhost:6379/0",
            app_factory=lambda broker: FakeCelery(),
        )
        self.assertEqual(dispatcher.dispatch("aiops.handle", {"task_id": "t-4"}), "celery-1")

    def test_metrics_registry_renders_prometheus_text(self):
        registry = MetricsRegistry()
        registry.increment("aiops_tasks_total", 2)
        self.assertIn("# TYPE aiops_tasks_total counter", registry.render())
        self.assertIn("aiops_tasks_total 2", registry.render())

    def test_http_metrics_endpoint_returns_prometheus_text(self):
        server = create_server(port=0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/metrics") as response:
                self.assertEqual(response.status, 200)
                self.assertIn("aiops_http_responses_total", response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_api_runs_end_to_end(self):
        server = create_server(port=0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(f"{base_url}/health") as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["status"], "healthy")

            payload = json.dumps({
                "service": "order-service",
                "metric": "cpu",
                "value": 95,
                "baseline": [40, 41, 39, 42, 40],
            }).encode("utf-8")
            request = Request(
                f"{base_url}/api/v1/incidents",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                created = json.loads(response.read())
                self.assertEqual(response.status, 201)
                task_id = created["task_id"]

            with urlopen(f"{base_url}/api/v1/tasks/{task_id}") as response:
                self.assertEqual(json.loads(response.read())["task_id"], task_id)

            bad_request = Request(
                f"{base_url}/api/v1/incidents",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as error:
                urlopen(bad_request)
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_api_rejects_json_array_body(self):
        server = create_server(port=0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/api/v1/incidents",
                data=b"[]",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_celery_incident_task_runs_core_workflow(self):
        try:
            from celery_app import celery_app
        except (ImportError, RuntimeError):
            self.skipTest("Celery 依赖未安装")
        result = celery_app.tasks["aiops.handle_incident"].run(
            service="order-service",
            metric="cpu",
            value=95,
            baseline=[40, 41, 39, 42, 40],
        )
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["task_type"], "aiops")


if __name__ == "__main__":
    unittest.main()
