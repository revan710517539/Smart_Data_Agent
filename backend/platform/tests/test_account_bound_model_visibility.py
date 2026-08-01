from __future__ import annotations

import http.client
import json
import threading
import unittest
from tempfile import TemporaryDirectory
from urllib.parse import quote

from backend.authz import normalize_tenant_id
from backend.platform.api.routes.analysis import _resolve_selected_model
from backend.platform.api.server import create_server
from backend.platform.bootstrap import build_local_platform
from backend.platform.settings.model_modules import list_models_for_application
from backend.platform.settings.store import account_system_config_scope


class AccountBoundModelVisibilityTest(unittest.TestCase):
    @staticmethod
    def _model(model_id: str = "account_bound_model") -> dict[str, object]:
        return {
            "id": model_id,
            "name": "账号绑定模型",
            "modelName": "中转站",
            "key": "https://account-model.example/v1",
            "value": "account-secret",
            "applicationModule": "",
            "availableModels": ["account-model"],
            "enabledModels": ["account-model"],
            "testStatus": "connected",
            "status": "available",
        }

    def test_system_config_reads_account_models_without_cross_account_leak(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            server.services.system_config_store.upsert_model(
                account_system_config_scope("u_super_admin"),
                self._model(),
                updated_by="u_super_admin",
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]

                def read(user_id: str, tenant_id: str) -> dict[str, object]:
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    conn.request(
                        "GET",
                        f"/api/system-config?tenant_id={quote(tenant_id)}&user_id={quote(user_id)}",
                    )
                    response = conn.getresponse()
                    return json.loads(response.read().decode("utf-8"))

                same_account = read("u_super_admin", "tenant_demo")
                other_institution = read("u_super_admin", normalize_tenant_id("郑州银行"))
                other_account = read("u_admin", "tenant_demo")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertIn("account_bound_model", {item["id"] for item in same_account["models"]})
        self.assertIn("account_bound_model", {item["id"] for item in other_institution["models"]})
        self.assertNotIn("account_bound_model", {item["id"] for item in other_account["models"]})

    def test_analysis_direct_selection_resolves_account_model(self) -> None:
        services = build_local_platform()
        try:
            services.system_config_store.upsert_model(
                account_system_config_scope("u_super_admin"),
                self._model("account_direct_selection"),
                updated_by="u_super_admin",
            )
            candidates = list_models_for_application(
                services.system_config_store,
                "tenant_demo",
                "intelligent_analysis_reasoning",
                user_id="u_super_admin",
                reveal_secret=True,
            )
            selected = _resolve_selected_model(
                services,
                "tenant_demo",
                {
                    "model_application_module": "intelligent_analysis_reasoning",
                    "model_application_selection": {
                        "integrationId": "account_direct_selection",
                        "selectedModelName": "account-model",
                    },
                },
                user_id="u_super_admin",
            )
        finally:
            services.close()

        self.assertIsNotNone(selected)
        self.assertEqual(selected["id"], "account_direct_selection")
        self.assertEqual(selected["value"], "account-secret")
        legacy = next(item for item in candidates if item["id"] == "account_direct_selection")
        self.assertEqual(legacy["applicationModule"], "intelligent_analysis_reasoning")
        self.assertTrue(legacy["legacyAccountBinding"])


if __name__ == "__main__":
    unittest.main()
