from __future__ import annotations

import http.client
import json
import os
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.platform.api.server import create_server


class DataAssetRelationshipProjectionTest(unittest.TestCase):
    def test_data_management_returns_only_table_to_table_relationships(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_root = root / "data"
            (data_root / "tenant_demo").mkdir(parents=True)
            with patch.dict(
                os.environ,
                {"SMART_DATA_AGENT_DATA_CRAWLER_ROOT": str(data_root)},
                clear=False,
            ):
                server = create_server("127.0.0.1", 0, root / "api.sqlite")

            store = server.services.lineage_store
            for edge in (
                {
                    "source_type": "dataset",
                    "source_id": "loan_operation_mart",
                    "target_type": "analysis_query",
                    "target_id": "task_123:query:1",
                    "edge_type": "reads",
                },
                {
                    "source_type": "analysis_query",
                    "source_id": "task_456:query:1",
                    "target_type": "dataset",
                    "target_id": "loan_operation_mart",
                    "edge_type": "derives",
                },
                {
                    "source_type": "raw_table",
                    "source_id": "loan_detail",
                    "target_type": "topic_table",
                    "target_id": "loan_summary",
                    "edge_type": "derives",
                },
                {
                    "source_type": "dataset",
                    "source_id": "loan_detail",
                    "target_type": "dataset",
                    "target_id": "loan_operation_mart",
                    "edge_type": "references",
                },
            ):
                store.record_edge("tenant_demo", edge, "u_super_admin")

            server.services.data_acquisition_service.csv_source.for_tenant("tenant_demo").prime_catalog()
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_address[1], timeout=5
                )
                connection.request(
                    "GET",
                    "/api/data-assets",
                    headers={
                        "X-User-Id": "u_super_admin",
                        "X-Tenant-Id": "tenant_demo",
                    },
                )
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(response.status, 200)
        relationships = payload["relationships"]
        self.assertEqual(payload["count"]["relationships"], 2)
        self.assertEqual(
            {
                (
                    relationship["source_type"],
                    relationship["source_id"],
                    relationship["target_type"],
                    relationship["target_id"],
                )
                for relationship in relationships
            },
            {
                ("raw_table", "loan_detail", "topic_table", "loan_summary"),
                ("dataset", "loan_detail", "dataset", "loan_operation_mart"),
            },
        )
        self.assertFalse(
            any(
                endpoint_type == "analysis_query"
                for relationship in relationships
                for endpoint_type in (
                    relationship["source_type"],
                    relationship["target_type"],
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
