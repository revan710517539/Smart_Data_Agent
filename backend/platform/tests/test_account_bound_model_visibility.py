from __future__ import annotations

import http.client
import json
import threading
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote

from backend.authz import normalize_tenant_id
from backend.platform.api.routes.analysis import _resolve_selected_model
from backend.platform.api.routes.settings import _available_system_parameter_scopes, handle_system_config_get
from backend.platform.api.server import create_server
from backend.platform.bootstrap import build_local_platform
from backend.platform.settings.model_modules import (
    RETIRED_DEFAULT_RELAY_MODEL_ID,
    list_models_for_application,
)
from backend.platform.settings.store import (
    GLOBAL_SYSTEM_CONFIG_TENANT,
    account_system_config_scope,
    system_config_external_code,
    system_config_storage_code,
    system_config_storage_locations,
    system_config_storage_prefix,
    system_config_storage_tenant,
)


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

    def test_unconfigured_system_config_does_not_inject_retired_default(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
                conn.request(
                    "GET",
                    f"/api/system-config?tenant_id={quote(normalize_tenant_id('华兴银行'))}&user_id=u_super_admin",
                )
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(response.status, 200)
        self.assertNotIn(RETIRED_DEFAULT_RELAY_MODEL_ID, {item["id"] for item in payload["models"]})
        self.assertFalse(any(item.get("requiresCredential") for item in payload["models"]))

    def test_analysis_runtime_config_exposes_account_models_for_any_institution(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            server.services.system_config_store.upsert_model(
                account_system_config_scope("u_super_admin"),
                {**self._model("account_runtime_model"), "applicationModule": "global_text_model"},
                updated_by="u_super_admin",
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]

                def read(tenant_id: str) -> dict[str, object]:
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    conn.request(
                        "GET",
                        f"/api/asr/fun-asr/runtime-config?tenant_id={quote(tenant_id)}&user_id=u_super_admin&application_module=realtime_voice_input",
                        headers={"X-User-Id": "u_super_admin", "X-Tenant-Id": quote(tenant_id)},
                    )
                    response = conn.getresponse()
                    return {"status": response.status, **json.loads(response.read().decode("utf-8"))}

                hankou = read(normalize_tenant_id("汉口银行"))
                huaxing = read(normalize_tenant_id("华兴银行"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(hankou["status"], 200)
        self.assertEqual(huaxing["status"], 200)
        hankou_ids = {item["id"] for item in hankou["analysisModels"]}
        huaxing_ids = {item["id"] for item in huaxing["analysisModels"]}
        self.assertEqual(hankou_ids, {"account_runtime_model"})
        self.assertEqual(hankou_ids, huaxing_ids)
        relay = next(item for item in hankou["analysisModels"] if item["id"] == "account_runtime_model")
        self.assertEqual(relay["applicationModule"], "global_text_model")
        self.assertEqual(relay["enabledModels"], ["account-model"])
        self.assertEqual(relay.get("value"), "")

    def test_system_config_skips_authorized_but_unprovisioned_parameter_scopes(self) -> None:
        class RelationalStoreStub:
            def get_model(self, tenant_id: str, model_id: str, reveal_secret: bool = False):
                return None

            def list_models(self, tenant_id: str, reveal_secret: bool = False):
                return []

            def list_speech_integrations(self, tenant_id: str, reveal_secret: bool = False):
                return []

            def list_system_params(self, tenant_id: str):
                if tenant_id != "tenant:sda-internal":
                    raise KeyError("tenant_not_provisioned")
                return [{"id": "ai_analysis_concurrency", "name": "AI分析并发上限", "value": "2", "category": "system", "description": ""}]

        repository = SimpleNamespace(
            list_user_assignments=lambda user_id: [SimpleNamespace(tenant_id="*")],
        )
        broker = SimpleNamespace(
            enforcer=SimpleNamespace(repository=repository),
            require_resource=lambda context, resource, action: None,
        )
        handler = SimpleNamespace(
            services=SimpleNamespace(system_config_store=RelationalStoreStub(), permission_broker=broker),
            _request_context=lambda params: SimpleNamespace(user_id="u_super_admin", tenant_id="tenant:sda-internal"),
            _require_system_config_permission=lambda context, action: None,
        )
        response: dict[str, object] = {}
        handler._send_json = lambda payload: response.update(payload)

        handle_system_config_get(handler, "")

        self.assertEqual(response["parameter_tenant_ids"], ["tenant:sda-internal"])
        self.assertTrue(response["can_read_system_params"])
        self.assertEqual(response["system_params"], [{
            "id": "ai_analysis_concurrency",
            "name": "AI分析并发上限",
            "value": "2",
            "category": "system",
            "description": "",
            "tenantId": "tenant:sda-internal",
            "institution": "sda-internal",
        }])

    def test_system_config_does_not_hide_other_parameter_store_failures(self) -> None:
        store = SimpleNamespace(
            list_system_params=lambda tenant_id: (_ for _ in ()).throw(KeyError("unexpected_store_failure")),
        )
        repository = SimpleNamespace(
            list_user_assignments=lambda user_id: [],
        )
        broker = SimpleNamespace(
            enforcer=SimpleNamespace(repository=repository),
            require_resource=lambda context, resource, action: None,
        )
        handler = SimpleNamespace(
            services=SimpleNamespace(system_config_store=store, permission_broker=broker),
        )

        with self.assertRaisesRegex(KeyError, "unexpected_store_failure"):
            _available_system_parameter_scopes(
                handler,
                SimpleNamespace(user_id="u_super_admin", tenant_id="tenant:sda-internal"),
            )

    def test_retired_default_is_never_routable(self) -> None:
        services = build_local_platform()
        try:
            services.system_config_store.upsert_model(
                account_system_config_scope("u_super_admin"),
                {**self._model(RETIRED_DEFAULT_RELAY_MODEL_ID), "applicationModule": "global_text_model"},
                updated_by="u_super_admin",
            )
            candidates = list_models_for_application(
                services.system_config_store,
                normalize_tenant_id("华兴银行"),
                "intelligent_analysis_reasoning",
                user_id="u_super_admin",
            )
        finally:
            services.close()

        self.assertNotIn(RETIRED_DEFAULT_RELAY_MODEL_ID, {item["id"] for item in candidates})

    def test_relational_virtual_scope_codes_are_global_isolated_and_reversible(self) -> None:
        first_scope = account_system_config_scope("u_super_admin")
        second_scope = account_system_config_scope("u_lina")
        first_code = system_config_storage_code(first_scope, "model_shared")
        second_code = system_config_storage_code(second_scope, "model_shared")

        self.assertEqual(system_config_storage_tenant(first_scope), "__global__")
        self.assertNotEqual(system_config_storage_prefix(first_scope), system_config_storage_prefix(second_scope))
        self.assertNotEqual(first_code, second_code)
        self.assertEqual(system_config_external_code(first_scope, first_code), "model_shared")
        self.assertEqual(
            system_config_storage_locations(first_scope),
            ((GLOBAL_SYSTEM_CONFIG_TENANT, "prefixed"), (first_scope, "raw")),
        )
        self.assertEqual(system_config_storage_locations("tenant:华兴银行"), (("tenant:华兴银行", "raw"),))

    def test_system_config_restores_leftover_tenant_models_and_speech_on_same_institution(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            store = server.services.system_config_store
            huaxing = normalize_tenant_id("华兴银行")
            zhengzhou = normalize_tenant_id("郑州银行")
            store.upsert_model(
                huaxing,
                {
                    "id": "model_1786295124248",
                    "name": "GPT等",
                    "modelName": "中转站",
                    "key": "https://legacy.example/v1",
                    "value": "legacy-gpt-secret",
                    "status": "available",
                },
                updated_by="u_super_admin",
            )
            store.upsert_speech_integration(
                huaxing,
                {
                    "id": "speech_1783531230043",
                    "name": "Fun-ASR",
                    "provider": "aliyun_fun_asr",
                    "apiBase": "https://legacy-asr.example/api/v1",
                    "apiKey": "legacy-asr-secret",
                    "status": "available",
                },
                updated_by="u_super_admin",
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]

                def read(tenant_id: str) -> dict[str, object]:
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    conn.request(
                        "GET",
                        f"/api/system-config?tenant_id={quote(tenant_id)}&user_id=u_super_admin",
                    )
                    response = conn.getresponse()
                    return {"status": response.status, **json.loads(response.read().decode("utf-8"))}

                same_institution = read(huaxing)
                other_institution = read(zhengzhou)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(same_institution["status"], 200)
        self.assertIn("model_1786295124248", {item["id"] for item in same_institution["models"]})
        self.assertIn("speech_1783531230043", {item["id"] for item in same_institution["speech_integrations"]})
        self.assertNotIn("legacy-gpt-secret", json.dumps(same_institution, ensure_ascii=False))
        self.assertNotIn("legacy-asr-secret", json.dumps(same_institution, ensure_ascii=False))
        self.assertNotIn("model_1786295124248", {item["id"] for item in other_institution["models"]})
        self.assertNotIn("speech_1783531230043", {item["id"] for item in other_institution["speech_integrations"]})

    def test_system_config_keeps_single_account_speech_when_leftover_exists(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            store = server.services.system_config_store
            huaxing = normalize_tenant_id("华兴银行")
            store.upsert_speech_integration(
                account_system_config_scope("u_super_admin"),
                {
                    "id": "speech_account_global",
                    "name": "Fun-ASR",
                    "provider": "aliyun_fun_asr",
                    "apiBase": "https://account-asr.example/api/v1",
                    "apiKey": "account-asr-secret",
                    "applicationModule": "global_voice_model",
                    "status": "available",
                },
                updated_by="u_super_admin",
            )
            store.upsert_speech_integration(
                huaxing,
                {
                    "id": "speech_tenant_leftover",
                    "name": "阿里云 Fun-ASR",
                    "provider": "aliyun_fun_asr",
                    "apiBase": "https://legacy-asr.example/api/v1",
                    "apiKey": "legacy-asr-secret",
                    "applicationModule": "popup_voice_input",
                    "status": "available",
                },
                updated_by="u_super_admin",
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request(
                    "GET",
                    f"/api/system-config?tenant_id={quote(huaxing)}&user_id=u_super_admin",
                )
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        speech_ids = [item["id"] for item in payload["speech_integrations"]]
        self.assertEqual(response.status, 200)
        self.assertEqual(speech_ids, ["speech_account_global"])
        self.assertEqual(payload["speech_integrations"][0]["applicationModule"], "global_voice_model")
        self.assertNotIn("legacy-asr-secret", json.dumps(payload, ensure_ascii=False))

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

    def test_system_config_hides_legacy_default_but_keeps_user_model(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            scope = account_system_config_scope("u_super_admin")
            server.services.system_config_store.upsert_model(
                scope,
                {**self._model(RETIRED_DEFAULT_RELAY_MODEL_ID), "name": "默认模型"},
                updated_by="u_super_admin",
            )
            server.services.system_config_store.upsert_model(
                scope,
                self._model("user_owned_model"),
                updated_by="u_super_admin",
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
                conn.request(
                    "GET",
                    f"/api/system-config?tenant_id={quote(normalize_tenant_id('华兴银行'))}&user_id=u_super_admin",
                )
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(response.status, 200)
        self.assertIn("user_owned_model", {item["id"] for item in payload["models"]})
        self.assertNotIn(RETIRED_DEFAULT_RELAY_MODEL_ID, {item["id"] for item in payload["models"]})

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

    def test_retired_default_id_cannot_be_created_through_api(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
                conn.request(
                    "POST",
                    "/api/system-config/model",
                    body=json.dumps(
                        {
                            "user_id": "u_super_admin",
                            "tenant_id": normalize_tenant_id("华兴银行"),
                            "model": self._model(RETIRED_DEFAULT_RELAY_MODEL_ID),
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                response = conn.getresponse()
                body = response.read().decode("utf-8")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(response.status, 400)
        self.assertNotIn("account-secret", body)

    def test_newly_registered_account_starts_without_implicit_model(self) -> None:
        password = "test-only-explicit-login-secret"
        with patch.dict("os.environ", {"SMART_DATA_AGENT_DEVELOPMENT_LOGIN_PASSWORD": password}):
            with TemporaryDirectory() as tmpdir:
                server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    port = server.server_address[1]
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    conn.request(
                        "POST",
                        "/api/auth/register",
                        body=json.dumps(
                            {
                                "name": "无预置模型用户",
                                "email": "default-model-user@example.com",
                                "password": password,
                                "institution": "华兴银行",
                            },
                            ensure_ascii=False,
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    response = conn.getresponse()
                    payload = json.loads(response.read().decode("utf-8"))
                    super_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    super_conn.request(
                        "POST",
                        "/api/auth/login",
                        body=json.dumps({"email": "xujingbo-jk@qifu.com", "password": "123456"}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    super_response = super_conn.getresponse()
                    super_cookie = super_response.getheader("Set-Cookie") or ""
                    approve_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    approve_conn.request(
                        "POST",
                        "/api/application/action",
                        body=json.dumps(
                            {
                                "module_key": "agent_workspace",
                                "action": "approve_registration",
                                "payload": {"requestId": payload.get("request_id")},
                            }
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json", "Cookie": super_cookie},
                    )
                    approve_response = approve_conn.getresponse()
                    approve_payload = json.loads(approve_response.read().decode("utf-8"))
                    user_id = approve_payload["result"]["user"]["user"]["id"]
                    if not user_id:
                        user_id = str(payload.get("request_id") or "")
                    saved = server.services.system_config_store.list_models(
                        account_system_config_scope(user_id), reveal_secret=True
                    )
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

        self.assertEqual(response.status, 202)
        self.assertEqual(approve_response.status, 200)
        self.assertEqual(saved, [])

    def test_tenant_admin_and_operator_can_bind_own_model_without_system_config_permission(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                cases = (
                    ("u_lina", normalize_tenant_id("华兴银行"), "lina_bound_model"),
                    ("u_zhaomin", normalize_tenant_id("郑州银行"), "zhaomin_bound_model"),
                )
                payloads: dict[str, dict[str, object]] = {}
                for user_id, tenant_id, model_id in cases:
                    model = {
                        **self._model(model_id),
                        "name": f"{user_id}绑定模型",
                        "key": f"https://{user_id}.example/v1",
                        "value": f"{user_id}-secret",
                    }
                    create_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    create_conn.request(
                        "POST",
                        "/api/system-config/model",
                        body=json.dumps(
                            {"user_id": user_id, "tenant_id": tenant_id, "model": model},
                            ensure_ascii=False,
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    create_response = create_conn.getresponse()
                    create_payload = json.loads(create_response.read().decode("utf-8"))

                    get_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    get_conn.request(
                        "GET",
                        f"/api/system-config?tenant_id={quote(tenant_id)}&user_id={user_id}",
                    )
                    get_response = get_conn.getresponse()
                    get_payload = json.loads(get_response.read().decode("utf-8"))

                    param_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    param_conn.request(
                        "POST",
                        "/api/system-config/system-param",
                        body=json.dumps(
                            {
                                "user_id": user_id,
                                "tenant_id": tenant_id,
                                "param": {
                                    "id": "analysis_user_concurrency_limit",
                                    "name": "AI分析并发",
                                    "value": "9",
                                    "category": "system",
                                    "description": "should stay admin gated",
                                },
                            },
                            ensure_ascii=False,
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    param_response = param_conn.getresponse()
                    param_payload = json.loads(param_response.read().decode("utf-8"))
                    payloads[user_id] = {
                        "create_status": create_response.status,
                        "create": create_payload,
                        "get_status": get_response.status,
                        "get": get_payload,
                        "param_status": param_response.status,
                        "param": param_payload,
                        "model_id": model_id,
                        "tenant_id": tenant_id,
                    }

                other_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                other_conn.request(
                    "GET",
                    f"/api/system-config?tenant_id={quote(normalize_tenant_id('郑州银行'))}&user_id=u_zhaomin",
                )
                other_response = other_conn.getresponse()
                other_payload = json.loads(other_response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        lina = payloads["u_lina"]
        zhaomin = payloads["u_zhaomin"]
        self.assertEqual(lina["create_status"], 200)
        self.assertEqual(zhaomin["create_status"], 200)
        self.assertEqual(lina["create"]["config_scope"], account_system_config_scope("u_lina"))
        self.assertEqual(zhaomin["create"]["config_scope"], account_system_config_scope("u_zhaomin"))
        self.assertEqual(lina["get_status"], 200)
        self.assertEqual(zhaomin["get_status"], 200)
        self.assertFalse(lina["get"]["can_read_system_params"])
        self.assertFalse(zhaomin["get"]["can_read_system_params"])
        self.assertEqual(lina["get"]["system_params"], [])
        self.assertEqual(zhaomin["get"]["system_params"], [])
        self.assertIn("lina_bound_model", {item["id"] for item in lina["get"]["models"]})
        self.assertIn("zhaomin_bound_model", {item["id"] for item in zhaomin["get"]["models"]})
        self.assertNotIn("lina_bound_model", {item["id"] for item in other_payload["models"]})
        self.assertEqual(lina["param_status"], 403)
        self.assertEqual(zhaomin["param_status"], 403)
        self.assertEqual(lina["param"]["error"], "permission_denied")
        self.assertEqual(zhaomin["param"]["error"], "permission_denied")


if __name__ == "__main__":
    unittest.main()
