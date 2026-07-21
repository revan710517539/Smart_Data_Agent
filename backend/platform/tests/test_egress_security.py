import socket
import unittest
from io import BytesIO
from urllib.error import HTTPError
from unittest.mock import patch

from backend.platform.security import EgressPolicyError, validate_outbound_url
from backend.platform.settings import call_model_completion, test_data_connection, test_model_integration, test_speech_integration
from backend.platform.settings.model_test import _classify_model_test_error, _provider_http_error_marker, _request_json_from_candidates


class _FakeHTTPResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        return self.payload[:limit] if limit >= 0 else self.payload


class EgressSecurityTest(unittest.TestCase):
    def test_public_https_host_is_allowed_after_dns_validation(self) -> None:
        with patch(
            "backend.platform.security.egress.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
        ):
            self.assertEqual(
                validate_outbound_url("https://models.example.com/v1"),
                "https://models.example.com/v1",
            )

    def test_loopback_private_link_local_and_non_https_targets_are_rejected(self) -> None:
        for url in (
            "https://127.0.0.1/admin",
            "https://10.12.0.3/internal",
            "https://169.254.169.254/latest/meta-data",
            "http://93.184.216.34/insecure",
        ):
            with self.subTest(url=url), self.assertRaises(EgressPolicyError):
                validate_outbound_url(url)

    def test_model_checks_can_explicitly_allow_public_http_relay(self) -> None:
        with patch(
            "backend.platform.security.egress.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 32520))],
        ):
            self.assertEqual(
                validate_outbound_url("http://models.example.com:32520/v1", allowed_schemes=("https", "http")),
                "http://models.example.com:32520/v1",
            )

    def test_production_requires_explicit_host_allowlist(self) -> None:
        with patch.dict("os.environ", {"SMART_DATA_AGENT_ENV": "production"}, clear=True):
            with self.assertRaises(EgressPolicyError):
                validate_outbound_url("https://93.184.216.34/v1")

        with patch.dict(
            "os.environ",
            {
                "SMART_DATA_AGENT_ENV": "production",
                "SMART_DATA_AGENT_EGRESS_ALLOWED_HOSTS": "models.example.com",
            },
            clear=True,
        ), patch(
            "backend.platform.security.egress.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
        ):
            self.assertEqual(
                validate_outbound_url("https://models.example.com/v1"),
                "https://models.example.com/v1",
            )
            with self.assertRaises(EgressPolicyError):
                validate_outbound_url("https://attacker.example/v1")

    def test_demo_model_and_speech_keys_are_never_reported_callable(self) -> None:
        model = test_model_integration(
            {
                "id": "demo_model",
                "name": "Demo model",
                "modelName": "中转站",
                "key": "https://example.local/v1",
                "value": "demo-key",
            }
        )
        speech = test_speech_integration(
            {
                "id": "demo_speech",
                "name": "Demo speech",
                "provider": "aliyun_fun_asr",
                "source": "阿里云",
                "apiBase": "https://example.local/v1",
                "apiKey": "demo-key",
            }
        )
        self.assertEqual(model["status"], "mock")
        self.assertFalse(model["callable"])
        self.assertEqual(speech["status"], "mock")
        self.assertFalse(speech["callable"])

    def test_model_integration_uses_development_http_relay_scheme(self) -> None:
        requests = []
        responses = [
            _FakeHTTPResponse(b'{"data":[{"id":"gpt-test"}]}'),
            _FakeHTTPResponse(b'{"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":1,"completion_tokens":1}}'),
        ]

        def fake_open(request, **kwargs):
            requests.append((request, kwargs))
            return responses.pop(0)

        with patch.dict("os.environ", {"SMART_DATA_AGENT_ENV": "development"}, clear=True), patch(
            "backend.platform.settings.model_test.safe_urlopen",
            side_effect=fake_open,
        ):
            result = test_model_integration(
                {
                    "id": "http_relay_model",
                    "name": "GPT",
                    "modelName": "中转站",
                    "key": "http://models.example.com:32520/",
                    "value": "real-key",
                }
            )

        self.assertTrue(result["callable"])
        self.assertEqual(result["used_model"], "gpt-test")
        self.assertEqual([request.full_url for request, _kwargs in requests], [
            "http://models.example.com:32520/v1/models",
            "http://models.example.com:32520/v1/chat/completions",
        ])
        self.assertEqual({kwargs["allowed_schemes"] for _request, kwargs in requests}, {("https", "http")})
        timeouts = [kwargs["timeout"] for _request, kwargs in requests]
        self.assertEqual(timeouts[0], 6)
        self.assertGreater(timeouts[1], 0)
        self.assertLessEqual(timeouts[1], 18)

    def test_model_integration_reports_unresolvable_domain(self) -> None:
        with patch(
            "backend.platform.security.egress.socket.getaddrinfo",
            side_effect=socket.gaierror("not found"),
        ):
            result = test_model_integration(
                {
                    "id": "bad_domain_model",
                    "name": "GPT",
                    "modelName": "中转站",
                    "key": "https://www.flaiverse.cc",
                    "value": "real-key",
                }
            )

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["callable"])
        self.assertIn("域名无法解析", result["message"])

    def test_model_integration_classifies_timeout_as_transient(self) -> None:
        with patch(
            "backend.platform.settings.model_test._fetch_relay_models",
            side_effect=RuntimeError("provider_timeout"),
        ):
            result = test_model_integration(
                {
                    "id": "slow_relay_model",
                    "name": "Gemini",
                    "modelName": "中转站",
                    "key": "https://models.example.com/v1",
                    "value": "real-key",
                }
            )
        self.assertEqual(result["error_code"], "request_timeout")
        self.assertTrue(result["transient"])
        self.assertIn("保留上次成功配置", result["message"])

    def test_gemini_location_error_is_preserved_over_fallback_404(self) -> None:
        with patch(
            "backend.platform.settings.model_test._request_json",
            side_effect=[
                RuntimeError("provider_http_400:user_location_not_supported"),
                RuntimeError("provider_http_404"),
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "user_location_not_supported"):
                _request_json_from_candidates(["https://example.com/v1/chat", "https://example.com/chat"], "key", method="POST")
        code, message, transient = _classify_model_test_error(RuntimeError("provider_http_400:user_location_not_supported"))
        self.assertEqual(code, "provider_location_unsupported")
        self.assertIn("中转站出口地区", message)
        self.assertFalse(transient)

    def test_gemini_location_error_marker_uses_sanitized_provider_body(self) -> None:
        error = HTTPError(
            "https://example.com/v1/chat/completions",
            400,
            "Bad Request",
            {},
            BytesIO(b'{"error":{"code":400,"message":"User location is not supported for the API use.","status":"FAILED_PRECONDITION"}}'),
        )
        self.assertEqual(_provider_http_error_marker(error), "user_location_not_supported")

    def test_explicit_submodel_retries_same_model_without_fallback(self) -> None:
        with patch(
            "backend.platform.settings.model_test._call_chat_completion",
            side_effect=[RuntimeError("temporary upstream error"), ("ok", {"prompt_tokens": 2, "completion_tokens": 1})],
        ) as call:
            result = call_model_completion(
                {
                    "id": "model_gpt",
                    "name": "GPT-5.5",
                    "modelName": "中转站",
                    "key": "https://models.example.com/v1",
                    "value": "real-key",
                    "availableModels": ["gpt-5.5"],
                    "enabledModels": ["gpt-5.5"],
                    "strictModelSelection": True,
                },
                "分析问题",
            )
        self.assertEqual(call.call_count, 2)
        self.assertEqual({item.args[2] for item in call.call_args_list}, {"gpt-5.5"})
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["used_model"], "gpt-5.5")

    def test_data_connection_test_uses_supplied_endpoint_credentials_catalog_and_query(self) -> None:
        requests = []
        responses = [
            _FakeHTTPResponse(b'{"datasets":[{"dataset_id":"loan_operation_mart","label":"Loan"}]}'),
            _FakeHTTPResponse(b'{"rows":[{"branch_name":"A","metric_value":12}]}'),
        ]

        def fake_open(request, **kwargs):
            requests.append(request)
            return responses.pop(0)

        with patch(
            "backend.platform.settings.connection_test.validate_outbound_url",
            return_value="https://data.example.com/api",
        ), patch(
            "backend.platform.settings.connection_test.safe_urlopen",
            side_effect=fake_open,
        ):
            result = test_data_connection(
                {
                    "id": "conn_real",
                    "tenant_id": "tenant_demo",
                    "institution": "华兴银行",
                    "sourceType": "毓数QBI",
                    "apiUrl": "https://data.example.com/api",
                    "account": "reader",
                    "password": "secret",
                    "dataset": "loan_operation_mart",
                    "mockEnabled": False,
                }
            )

        self.assertEqual(result["status"], "verified")
        self.assertTrue(result["verified"])
        self.assertEqual(result["sample"]["rows"][0]["metric_value"], 12)
        self.assertEqual([request.full_url for request in requests], [
            "https://data.example.com/api/datasets",
            "https://data.example.com/api/query",
        ])
        self.assertTrue(requests[0].get_header("Authorization").startswith("Basic "))


if __name__ == "__main__":
    unittest.main()
