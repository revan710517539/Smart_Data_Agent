from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.platform.api.routes.analysis import run_analysis
from backend.platform.bootstrap import build_local_platform
from backend.platform.api.support import format_prometheus_metrics
from backend.platform.observability import RuntimeEvent
from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse


class LocalConcurrencyTest(unittest.TestCase):
    def test_prometheus_counters_are_all_time_monotonic_not_a_rolling_sample(self) -> None:
        with TemporaryDirectory() as tmpdir:
            services = build_local_platform(Path(tmpdir) / "metrics.sqlite")
            try:
                for index in range(250):
                    services.task_repository.save_runtime_event(
                        RuntimeEvent(
                            event_type="analysis.run",
                            trace_id=f"trace_{index}",
                            tenant_id="tenant_demo",
                            user_id="u_super_admin",
                            status="error" if index % 10 == 0 else "ok",
                            latency_ms=index,
                            fallback_used=index % 20 == 0,
                        )
                    )
                summary = services.task_repository.runtime_summary()
                self.assertEqual(summary["sample_size"], 250)
                self.assertEqual(summary["ok_count"], 225)
                self.assertEqual(summary["error_count"], 25)
                self.assertEqual(summary["latency_sum_ms"], sum(range(250)))
                metrics = format_prometheus_metrics(summary)
                self.assertIn('smart_data_agent_analysis_requests_total{status="ok"} 225', metrics)
                self.assertIn(f"smart_data_agent_analysis_latency_ms_sum {sum(range(250))}", metrics)
            finally:
                services.close()

    def test_threaded_sqlite_adapter_serializes_transactions_without_cross_thread_misuse(self) -> None:
        with TemporaryDirectory() as tmpdir:
            services = build_local_platform(Path(tmpdir) / "platform.sqlite")
            attach_governed_test_warehouse(services)
            try:
                with ThreadPoolExecutor(max_workers=8) as executor:
                    futures = [
                        executor.submit(
                            run_analysis,
                            services,
                            "u_super_admin",
                            "tenant_demo",
                            f"各分行放款金额并发样本 {index}",
                            {"request_id": f"concurrency_{index}"},
                        )
                        for index in range(30)
                    ]
                    results = [future.result() for future in as_completed(futures)]
                self.assertEqual(len(results), 30)
                self.assertEqual(len({result["task_id"] for result in results}), 30)
                self.assertEqual(len({result["trace_id"] for result in results}), 30)
                self.assertTrue(all(result["status"] in {"completed", "review_required"} for result in results))
                self.assertEqual(services.task_repository.runtime_summary()["ok_count"], 30)
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
