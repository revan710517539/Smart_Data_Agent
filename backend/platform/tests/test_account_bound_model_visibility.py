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
from backend.platform.settings import (
    DEFAULT_MODEL_TEMPLATE_SCOPE,
    DEFAULT_RELAY_MODEL_ID,
    configure_default_relay_model,
    ensure_default_models_for_account,
)
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

    def test_default_relay_is_backfilled_for_existing_accounts_without_overwrite(self) -> None:
        services = build_local_platform()
        try:
            configure_default_relay_model(services.system_config_store, "test-default-secret")
            self.assertEqual(ensure_default_models_for_account(services.system_config_store, "u_super_admin"), [DEFAULT_RELAY_MODEL_ID])
            default_model = services.system_config_store.get_model(
                account_system_config_scope("u_super_admin"),
                DEFAULT_RELAY_MODEL_ID,
                reveal_secret=True,
            )
            template = services.system_config_store.get_model(
                DEFAULT_MODEL_TEMPLATE_SCOPE,
                DEFAULT_RELAY_MODEL_ID,
                reveal_secret=True,
            )
            self.assertIsNotNone(default_model)
            self.assertEqual(default_model["key"], "https://litellm-dev.sandbox.deepbank.daikuan.qihoo.net")
            self.assertEqual(default_model["value"], "test-default-secret")
            self.assertEqual(template["value"], "test-default-secret")
            self.assertEqual(default_model["status"], "draft")

            services.system_config_store.upsert_model(
                account_system_config_scope("u_admin"),
                {
                    **self._model(DEFAULT_RELAY_MODEL_ID),
                    "name": "账号保留模型",
                    "key": "https://custom.example/v1",
                },
                updated_by="u_admin",
            )
            self.assertEqual(ensure_default_models_for_account(services.system_config_store, "u_admin"), [])
            preserved = services.system_config_store.get_model(
                account_system_config_scope("u_admin"), DEFAULT_RELAY_MODEL_ID, reveal_secret=True
            )
            self.assertEqual(preserved["key"], "https://custom.example/v1")
        finally:
            services.close()

    def test_new_model_saved_in_one_institution_is_visible_to_the_same_account_elsewhere(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                tenant_id = normalize_tenant_id("华兴银行")
                other_tenant_id = normalize_tenant_id("郑州银行")
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request(
                    "POST",
                    "/api/system-config/model",
                    body=json.dumps(
                        {"user_id": "u_super_admin", "tenant_id": tenant_id, "model": self._model("account_created_model")},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                create_response = conn.getresponse()
                create_payload = json.loads(create_response.read().decode("utf-8"))

                read_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                read_conn.request(
                    "GET",
                    f"/api/system-config?tenant_id={quote(other_tenant_id)}&user_id=u_super_admin",
                )
                read_response = read_conn.getresponse()
                read_payload = json.loads(read_response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(create_response.status, 200)
        self.assertEqual(create_payload["config_scope"], account_system_config_scope("u_super_admin"))
        self.assertEqual(read_response.status, 200)
        self.assertEqual(read_payload["model_config_scope"], account_system_config_scope("u_super_admin"))
        matching = next(item for item in read_payload["models"] if item["id"] == "account_created_model")
        self.assertEqual(matching["value"], "******")

    def test_newly_registered_account_does_not_reseed_a_deleted_default_relay(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            configure_default_relay_model(server.services.system_config_store, "test-default-secret")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request(
                    "POST",
                    "/api/auth/register",
                    body=json.dumps(
                        {"name": "默认模型用户", "email": "default-model-user@example.com", "institution": "华兴银行"},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
                user_id = payload["user"]["id"]
                saved = server.services.system_config_store.get_model(
                    account_system_config_scope(user_id), DEFAULT_RELAY_MODEL_ID, reveal_secret=True
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(response.status, 201)
        self.assertIsNone(saved)


if __name__ == "__main__":
    unittest.main()
