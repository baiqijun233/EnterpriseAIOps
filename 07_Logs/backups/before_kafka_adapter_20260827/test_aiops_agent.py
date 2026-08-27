import sys
import unittest
import json
import tempfile
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "02_Source" / "agent_tech_portfolio"
sys.path.insert(0, str(SOURCE))

from aiops_agent import AIOpsOrchestrator, Alert
from api_server import create_server
from common.storage import TaskStore


class AIOpsAgentTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
