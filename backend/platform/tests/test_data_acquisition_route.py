from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.platform.api.routes.data_acquisition import handle_data_acquisition_get


class DataAcquisitionRouteTest(unittest.TestCase):
    def test_response_counts_only_list_collections(self) -> None:
        bundle = {
            "sources": [],
            "script_versions": [],
            "jobs": [],
            "runs": [],
            "repair_proposals": [],
            "quality_results": [],
            "source_mode": "csv_folder",
            "source_read_only": True,
            "csv_source": {"file_count": 3},
        }

        class Handler:
            services = SimpleNamespace(
                data_acquisition_service=SimpleNamespace(bundle=lambda _tenant_id: bundle),
            )
            payload: dict | None = None

            def _request_context(self, *, params: dict) -> SimpleNamespace:
                return SimpleNamespace(tenant_id="tenant:华兴银行", user_id="u_super_admin")

            def _require_asset_permission(self, _context: SimpleNamespace, _action: str) -> None:
                return None

            def _send_json(self, payload: dict, *_args: object, **_kwargs: object) -> None:
                self.payload = payload

        handler = Handler()
        handle_data_acquisition_get(handler, "")

        self.assertIsNotNone(handler.payload)
        assert handler.payload is not None
        self.assertEqual(handler.payload["count"], {
            "sources": 0,
            "script_versions": 0,
            "jobs": 0,
            "runs": 0,
            "repair_proposals": 0,
            "quality_results": 0,
        })
        self.assertEqual(handler.payload["csv_source"], {"file_count": 3})


if __name__ == "__main__":
    unittest.main()
