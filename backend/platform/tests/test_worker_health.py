from __future__ import annotations

import json
import os
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.platform.api.server import _external_worker_health
from backend.platform.automation.runtime import AutomationWorker


class _IdleStore:
    def __init__(self, observed: threading.Event) -> None:
        self.observed = observed

    def enqueue_due_tasks(self, *, limit: int) -> list[object]:
        self.observed.set()
        return []


class _IdleRuntime:
    def __init__(self, observed: threading.Event) -> None:
        self.store = _IdleStore(observed)

    def run_once(self, worker_id: str) -> None:
        return None

    def process_notifications_once(self) -> int:
        return 0


class WorkerHealthTest(unittest.TestCase):
    def test_worker_publishes_atomic_heartbeat_and_marks_stop(self) -> None:
        with TemporaryDirectory() as tmpdir:
            health_path = Path(tmpdir) / "runtime" / "worker-health.json"
            observed = threading.Event()
            worker = AutomationWorker(
                _IdleRuntime(observed),
                poll_seconds=0.1,
                worker_id="worker-test",
                health_path=health_path,
            )
            worker.start()
            self.assertTrue(observed.wait(timeout=2))
            deadline = time.monotonic() + 2
            while not health_path.is_file() and time.monotonic() < deadline:
                time.sleep(0.01)
            running = json.loads(health_path.read_text(encoding="utf-8"))
            self.assertEqual(running["schema_version"], "smart-data-agent-worker-health/v1")
            self.assertEqual(running["worker_id"], "worker-test")
            self.assertTrue(running["ready"])
            worker.close()
            stopped = json.loads(health_path.read_text(encoding="utf-8"))
            self.assertFalse(stopped["ready"])
            self.assertFalse(any(path.name.endswith(".tmp") for path in health_path.parent.iterdir()))

    def test_external_worker_health_accepts_fresh_contract_and_rejects_stale_or_bad_schema(self) -> None:
        with TemporaryDirectory() as tmpdir:
            health_path = Path(tmpdir) / "worker-health.json"
            with patch.dict(os.environ, {"SMART_DATA_AGENT_WORKER_HEALTH_FILE": str(health_path)}, clear=False):
                self._write_health(health_path, heartbeat_at=datetime.now(timezone.utc))
                self.assertTrue(_external_worker_health(True)["ready"])

                self._write_health(health_path, heartbeat_at=datetime.now(timezone.utc) - timedelta(seconds=31))
                stale = _external_worker_health(True)
                self.assertFalse(stale["ready"])
                self.assertEqual(stale["error"], "external_worker_heartbeat_stale")

                self._write_health(health_path, heartbeat_at=datetime.now(timezone.utc), schema="wrong/v1")
                incompatible = _external_worker_health(True)
                self.assertFalse(incompatible["ready"])
                self.assertEqual(incompatible["error"], "external_worker_heartbeat_unavailable")

    @staticmethod
    def _write_health(
        path: Path,
        *,
        heartbeat_at: datetime,
        schema: str = "smart-data-agent-worker-health/v1",
    ) -> None:
        path.write_text(
            json.dumps(
                {
                    "schema_version": schema,
                    "ready": True,
                    "worker_id": "worker-candidate",
                    "heartbeat_at": heartbeat_at.isoformat(),
                    "last_error_at": None,
                    "last_error_code": None,
                }
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
