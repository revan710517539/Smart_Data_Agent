from __future__ import annotations

import http.client
import json
import threading
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch
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
                other_account_models = server.services.system_config_store.list_models_owned_by(
                    "u_lina", normalize_tenant_id("华兴银行")
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertIn("account_bound_model", {item["id"] for item in same_account["models"]})
        self.assertIn("account_bound_model", {item["id"] for item in other_institution["models"]})
        self.assertNotIn("account_bound_model", {item["id"] for item in other_account_models})

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
                account_system_config_scope("u_lina"),
                {
                    **self._model(DEFAULT_RELAY_MODEL_ID),
                    "name": "账号保留模型",
                    "key": "https://custom.example/v1",
                },
                updated_by="u_lina",
            )
            self.assertEqual(ensure_default_models_for_account(services.system_config_store, "u_lina"), [])
            preserved = services.system_config_store.get_model(
                account_system_config_scope("u_lina"), DEFAULT_RELAY_MODEL_ID, reveal_secret=True
            )
            self.assertEqual(preserved["key"], "https://litellm-dev.sandbox.deepbank.daikuan.qihoo.net")
            self.assertEqual(preserved["applicationModule"], "global_text_model")
        finally:
            services.close()

    def test_connected_super_admin_default_repairs_blank_template_and_account_shell(self) -> None:
        services = build_local_platform()
        try:
            connected_default = {
                **self._model(DEFAULT_RELAY_MODEL_ID),
                "name": "旧默认中转模型",
                "key": "https://litellm-dev.sandbox.deepbank.daikuan.qihoo.net",
                "availableModels": ["360/deepseek-v4-flash"],
                "enabledModels": ["360/deepseek-v4-flash"],
            }
            services.system_config_store.upsert_model(
                account_system_config_scope("u_super_admin"),
                connected_default,
                updated_by="u_super_admin",
            )
            services.system_config_store.upsert_model(
                account_system_config_scope("u_lina"),
                {
                    **connected_default,
                    "value": "stale-secret",
                    "availableModels": [],
                    "enabledModels": [],
                    "testStatus": "untested",
                    "status": "draft",
                },
                updated_by="u_lina",
            )

            ensure_default_models_for_account(services.system_config_store, "u_lina")
            template = services.system_config_store.get_model(
                DEFAULT_MODEL_TEMPLATE_SCOPE, DEFAULT_RELAY_MODEL_ID, reveal_secret=True
            )
            restored = services.system_config_store.get_model(
                account_system_config_scope("u_lina"), DEFAULT_RELAY_MODEL_ID, reveal_secret=True
            )
        finally:
            services.close()

        self.assertEqual(template["status"], "available")
        self.assertEqual(template["name"], "默认模型")
        self.assertEqual(template["enabledModels"], ["360/deepseek-v4-flash"])
        self.assertEqual(restored["value"], "account-secret")
        self.assertEqual(restored["enabledModels"], ["360/deepseek-v4-flash"])

    def test_fresh_local_platform_has_no_synthetic_admin_account(self) -> None:
        with TemporaryDirectory() as tmpdir:
            services = build_local_platform(f"{tmpdir}/api.sqlite")
            try:
                profile = services.access_service.user_store.get_profile("u_admin")
                assignments = services.permission_broker.enforcer.repository.list_user_assignments("u_admin")
                super_profile = services.access_service.user_store.get_profile("u_super_admin")
            finally:
                services.close()

        self.assertIsNone(profile)
        self.assertEqual(assignments, [])
        self.assertIsNotNone(super_profile)

    def test_startup_canonicalizes_existing_account_defaults(self) -> None:
        with TemporaryDirectory() as tmpdir, patch.dict(
            "os.environ", {"SMART_DATA_AGENT_DEFAULT_MODEL_API_KEY": "startup-default-secret"}
        ):
            db_path = f"{tmpdir}/api.sqlite"
            services = build_local_platform(db_path)
            try:
                services.system_config_store.upsert_model(
                    account_system_config_scope("u_lina"),
                    {
                        **self._model(DEFAULT_RELAY_MODEL_ID),
                        "name": "历史默认模型名称",
                        "key": "https://stale.example/v1",
                        "applicationModule": "intelligent_analysis_reasoning",
                    },
                    updated_by="u_lina",
                )
            finally:
                services.close()

            rebuilt = build_local_platform(db_path)
            try:
                saved = rebuilt.system_config_store.get_model(
                    account_system_config_scope("u_lina"), DEFAULT_RELAY_MODEL_ID, reveal_secret=True
                )
            finally:
                rebuilt.close()

        self.assertEqual(saved["name"], "默认模型")
        self.assertEqual(saved["key"], "https://litellm-dev.sandbox.deepbank.daikuan.qihoo.net")
        self.assertEqual(saved["applicationModule"], "global_text_model")

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
        self.assertEqual(matching["applicationModule"], "global_text_model")

    def test_deleted_account_model_does_not_reappear_from_legacy_tenant_copy(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            model = self._model("deleted_model")
            server.services.system_config_store.upsert_model(
                account_system_config_scope("u_super_admin"), model, updated_by="u_super_admin"
            )
            server.services.system_config_store.upsert_model(
                normalize_tenant_id("华兴银行"), {**model, "name": "机构旧副本"}, updated_by="u_super_admin"
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                tenant = quote(normalize_tenant_id("华兴银行"))
                delete_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                delete_conn.request("DELETE", f"/api/system-config/model?tenant_id={tenant}&user_id=u_super_admin&model_id=deleted_model")
                delete_response = delete_conn.getresponse()
                delete_payload = json.loads(delete_response.read().decode("utf-8"))
                read_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                read_conn.request("GET", f"/api/system-config?tenant_id={tenant}&user_id=u_super_admin")
                read_response = read_conn.getresponse()
                read_payload = json.loads(read_response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(delete_response.status, 200)
        self.assertTrue(delete_payload["deleted"])
        self.assertNotIn("deleted_model", {item["id"] for item in read_payload["models"]})

    def test_default_relay_is_canonical_for_every_account_and_cannot_be_deleted(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            configure_default_relay_model(server.services.system_config_store, "test-default-secret")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                for user_id, tenant_id in (("u_super_admin", normalize_tenant_id("华兴银行")),):
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    conn.request(
                        "GET",
                        f"/api/system-config?tenant_id={quote(tenant_id)}&user_id={user_id}",
                    )
                    response = conn.getresponse()
                    payload = json.loads(response.read().decode("utf-8"))
                    default = next(item for item in payload["models"] if item["id"] == DEFAULT_RELAY_MODEL_ID)
                    self.assertEqual(default["key"], "https://litellm-dev.sandbox.deepbank.daikuan.qihoo.net")
                    self.assertEqual(default["applicationModule"], "global_text_model")

                ensure_default_models_for_account(server.services.system_config_store, "u_lina")
                account_default = server.services.system_config_store.get_model(
                    account_system_config_scope("u_lina"), DEFAULT_RELAY_MODEL_ID, reveal_secret=True
                )
                self.assertEqual(account_default["key"], "https://litellm-dev.sandbox.deepbank.daikuan.qihoo.net")
                self.assertEqual(account_default["applicationModule"], "global_text_model")

                delete_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                delete_conn.request(
                    "DELETE",
                    f"/api/system-config/model?tenant_id={quote(normalize_tenant_id('华兴银行'))}&user_id=u_super_admin&model_id={DEFAULT_RELAY_MODEL_ID}",
                )
                delete_response = delete_conn.getresponse()
                delete_body = delete_response.read().decode("utf-8")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(delete_response.status, 400)
        self.assertNotIn("test-default-secret", delete_body)

    def test_newly_registered_account_receives_the_protected_default_relay(self) -> None:
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
        self.assertIsNotNone(saved)
        self.assertEqual(saved["applicationModule"], "global_text_model")
        self.assertEqual(saved["key"], "https://litellm-dev.sandbox.deepbank.daikuan.qihoo.net")


if __name__ == "__main__":
    unittest.main()
