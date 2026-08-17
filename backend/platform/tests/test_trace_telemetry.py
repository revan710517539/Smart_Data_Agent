from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.platform.api.routes.analysis import run_analysis
from backend.platform.bootstrap import build_local_platform
from backend.platform.observability import TraceRecorder
from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse


class TraceTelemetryTest(unittest.TestCase):
    def test_nested_span_records_parent_duration_and_stable_error_code(self) -> None:
        recorder = TraceRecorder()
        trace_id = recorder.start_trace()
        with recorder.span("root", {"tenant": "tenant_demo"}) as root_output:
            root_output["result"] = "ok"
            with self.assertRaisesRegex(RuntimeError, "boom"):
                with recorder.span("child"):
                    raise RuntimeError("boom")
        spans = recorder.spans()
        self.assertEqual([span.span_id for span in spans], ["span_0002", "span_0001"])
        child, root = spans
        self.assertEqual(child.trace_id, trace_id)
        self.assertEqual(child.parent_span_id, root.span_id)
        self.assertEqual(child.status, "error")
        self.assertEqual(child.error_code, "RuntimeError")
        self.assertIsNotNone(root.ended_at)
        self.assertGreaterEqual(root.duration_ms, 0)

    def test_persisted_trace_query_is_tenant_scoped(self) -> None:
        with TemporaryDirectory() as tmpdir:
            services = build_local_platform(Path(tmpdir) / "platform.sqlite")
            attach_governed_test_warehouse(services)
            try:
                task = run_analysis(services, "u_super_admin", "tenant_demo", "各分行放款金额")
                trace_id = str(task["trace_id"])
                self.assertTrue(services.task_repository.trace_belongs_to_tenant("tenant_demo", trace_id))
                self.assertFalse(services.task_repository.trace_belongs_to_tenant("tenant_other", trace_id))
                spans = services.task_repository.trace_spans(trace_id)
                self.assertGreater(len(spans), 0)
                self.assertTrue(all(span["trace_id"] == trace_id for span in spans))
                self.assertTrue(all("duration_ms" in span and "span_kind" in span for span in spans))
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
