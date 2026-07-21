from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.platform.api.routes.asr import (
    FunAsrProxy,
    _public_fun_asr_error,
    _resolve_fun_asr_api_key,
    _resolve_fun_asr_speech_integration,
    build_continue_task_event,
    build_fun_asr_endpoint,
    build_run_task_event,
    dashscope_api_base_to_fun_asr_endpoint,
    extract_fun_asr_transcript,
)
from backend.platform.api.server import _websocket_session_token


class FunAsrProxyContractTest(unittest.TestCase):
    def test_builds_workspace_scoped_endpoint(self) -> None:
        self.assertEqual(
            build_fun_asr_endpoint("ws-test", "cn-beijing"),
            "wss://ws-test.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference",
        )
        self.assertEqual(
            build_fun_asr_endpoint("ws-test", "ap-southeast-1"),
            "wss://ws-test.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/inference",
        )

    def test_converts_dashscope_http_api_base_to_fun_asr_websocket_endpoint(self) -> None:
        self.assertEqual(
            dashscope_api_base_to_fun_asr_endpoint("https://ws-nvbkaw0atdgdbvv7.cn-beijing.maas.aliyuncs.com/api/v1"),
            "wss://ws-nvbkaw0atdgdbvv7.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference",
        )
        self.assertEqual(
            build_fun_asr_endpoint("ignored", "cn-beijing", api_base="https://ws-nvbkaw0atdgdbvv7.cn-beijing.maas.aliyuncs.com/api/v1"),
            "wss://ws-nvbkaw0atdgdbvv7.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference",
        )

    def test_run_task_event_matches_fun_asr_realtime_contract(self) -> None:
        context = [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "周报分析"}],
            }
        ]
        event = build_run_task_event(
            "2bf83b9a-baeb-4fda-8d9a-111111111111",
            model="fun-asr-realtime",
            sample_rate=16000,
            context=context,
        )

        self.assertEqual(event["header"]["action"], "run-task")
        self.assertEqual(event["header"]["streaming"], "duplex")
        self.assertEqual(event["payload"]["task_group"], "audio")
        self.assertEqual(event["payload"]["task"], "asr")
        self.assertEqual(event["payload"]["function"], "recognition")
        self.assertEqual(event["payload"]["model"], "fun-asr-realtime")
        self.assertEqual(event["payload"]["parameters"]["format"], "pcm")
        self.assertEqual(event["payload"]["parameters"]["sample_rate"], 16000)
        self.assertEqual(event["payload"]["input"]["context"], context)

    def test_continue_task_event_preserves_context(self) -> None:
        context = [
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "已完成经营分析"}],
            }
        ]
        event = build_continue_task_event("2bf83b9a-baeb-4fda-8d9a-111111111111", context=context)

        self.assertEqual(event["header"]["action"], "continue-task")
        self.assertEqual(event["header"]["streaming"], "duplex")
        self.assertEqual(event["payload"]["input"]["context"], context)

    def test_extracts_incremental_and_final_transcript(self) -> None:
        incremental = extract_fun_asr_transcript(
            {
                "header": {"event": "result-generated"},
                "payload": {
                    "output": {
                        "sentence": {
                            "text": "分析上海分行",
                            "sentence_end": False,
                        }
                    }
                },
            }
        )
        final = extract_fun_asr_transcript(
            {
                "header": {"event": "result-generated"},
                "payload": {
                    "output": {
                        "sentence": {
                            "text": "分析上海分行本周余额达成",
                            "sentence_end": True,
                        }
                    }
                },
            }
        )

        self.assertEqual(incremental, {"type": "transcript", "text": "分析上海分行", "final": False, "beginTime": None, "endTime": None})
        self.assertEqual(final, {"type": "transcript", "text": "分析上海分行本周余额达成", "final": True, "beginTime": None, "endTime": None})

    def test_extracts_session_token_from_websocket_protocols(self) -> None:
        self.assertEqual(_websocket_session_token("vite-hmr"), "")
        self.assertEqual(_websocket_session_token("sda-session,sda1.token.signature"), "sda1.token.signature")
        self.assertEqual(_websocket_session_token("chat, sda-session, sda1.token.signature"), "sda1.token.signature")

    def test_resolves_only_standard_dashscope_api_key(self) -> None:
        with patch.dict("os.environ", {"DASHSCOPE_API_KEY": "sk-dashscope"}, clear=True):
            self.assertEqual(_resolve_fun_asr_api_key(object(), "tenant_demo", {}, {}), "sk-dashscope")
        with patch.dict("os.environ", {"FUN_ASR_API_KEY": "sk-custom"}, clear=True):
            self.assertEqual(_resolve_fun_asr_api_key(object(), "tenant_demo", {}, {}), "")

    def test_system_speech_integration_api_key_takes_precedence(self) -> None:
        with patch.dict("os.environ", {"DASHSCOPE_API_KEY": "sk-env"}, clear=True):
            self.assertEqual(
                _resolve_fun_asr_api_key(
                    object(),
                    "tenant_demo",
                    {},
                    {},
                    {"apiKey": "sk-configured-speech"},
                ),
                "sk-configured-speech",
            )

    def test_resolved_config_uses_only_api_base_key_and_fixed_fun_asr_model(self) -> None:
        class Store:
            def list_speech_integrations(self, tenant_id: str, reveal_secret: bool = False) -> list[dict[str, str]]:
                return [
                    {
                        "id": "speech_test",
                        "provider": "aliyun_fun_asr",
                        "apiBase": "https://ws-config.cn-beijing.maas.aliyuncs.com/api/v1",
                        "apiKey": "sk-configured-speech",
                        "workspaceId": "ws-legacy",
                        "region": "ap-southeast-1",
                        "modelName": "legacy-model",
                        "status": "available",
                    }
                ]

        handler = SimpleNamespace(services=SimpleNamespace(system_config_store=Store()))
        proxy = FunAsrProxy(handler, object(), {}, "tenant_demo", "u_admin")
        with patch.dict(
            "os.environ",
            {
                "DASHSCOPE_API_KEY": "sk-env",
                "FUN_ASR_MODEL": "env-model",
                "FUN_ASR_REGION": "ap-southeast-1",
                "FUN_ASR_WORKSPACE_ID": "ws-env",
            },
            clear=True,
        ):
            config = proxy._resolve_config(
                {"workspaceId": "ws-event", "region": "ap-southeast-1", "model": "event-model"},
                sample_rate=16000,
            )

        self.assertEqual(config.endpoint, "wss://ws-config.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference")
        self.assertEqual(config.api_key, "sk-configured-speech")
        self.assertEqual(config.model, "fun-asr-realtime")
        self.assertFalse(hasattr(config, "workspace_id"))
        self.assertFalse(hasattr(config, "region"))

    def test_runtime_prefers_verified_account_fun_asr_over_tenant_demo_seed(self) -> None:
        demo = {
            "id": "speech_fun_asr",
            "name": "阿里云 Fun-ASR",
            "provider": "aliyun_fun_asr",
            "apiBase": "https://ws-demo.cn-beijing.maas.aliyuncs.com/api/v1",
            "apiKey": "dashscope-demo-key",
            "status": "available",
            "testStatus": "mock",
        }
        verified = {
            "id": "speech_verified",
            "name": "阿里云 Fun-ASR",
            "provider": "aliyun_fun_asr",
            "apiBase": "https://ws-real.cn-beijing.maas.aliyuncs.com/api/v1",
            "apiKey": "sk-real",
            "status": "available",
            "testStatus": "connected",
        }

        class Store:
            def list_speech_integrations(self, tenant_id: str, reveal_secret: bool = False):
                return [demo]

            def list_speech_integrations_owned_by(self, user_id: str, tenant_id: str, reveal_secret: bool = False):
                return [verified, demo]

        handler = SimpleNamespace(services=SimpleNamespace(system_config_store=Store()))
        selected = _resolve_fun_asr_speech_integration(
            handler,
            "tenant_demo",
            {"provider": "aliyun_fun_asr"},
            {},
            "u_super_admin",
        )
        self.assertEqual(selected["id"], "speech_verified")
        self.assertEqual(selected["testStatus"], "connected")

    def test_runtime_selects_verified_fun_asr_by_speech_application_module(self) -> None:
        realtime = {
            "id": "speech_realtime", "name": "实时语音模型", "provider": "aliyun_fun_asr",
            "apiBase": "https://realtime.example/api/v1", "apiKey": "sk-realtime",
            "applicationModule": "realtime_voice_input", "status": "available", "testStatus": "connected",
        }
        popup = {
            "id": "speech_popup", "name": "弹窗语音模型", "provider": "aliyun_fun_asr",
            "apiBase": "https://popup.example/api/v1", "apiKey": "sk-popup",
            "applicationModule": "popup_voice_input", "status": "available", "testStatus": "connected",
        }

        class Store:
            def list_speech_integrations(self, tenant_id: str, reveal_secret: bool = False):
                return [realtime, popup]

        handler = SimpleNamespace(services=SimpleNamespace(system_config_store=Store()))
        selected = _resolve_fun_asr_speech_integration(
            handler, "tenant_demo", {"applicationModule": "popup_voice_input"}, {}, "u_admin",
        )
        self.assertEqual(selected["id"], "speech_popup")
        rejected = _resolve_fun_asr_speech_integration(
            handler,
            "tenant_demo",
            {"speechIntegrationId": "speech_realtime", "applicationModule": "popup_voice_input"},
            {},
            "u_admin",
        )
        self.assertEqual(rejected, {})

    def test_runtime_selects_saved_fun_asr_without_connectivity_test(self) -> None:
        untested = {
            "id": "speech_untested", "name": "未测试语音模型", "provider": "aliyun_fun_asr",
            "apiBase": "https://speech.example/api/v1", "apiKey": "sk-configured",
            "applicationModule": "realtime_voice_input", "status": "draft", "testStatus": "untested",
        }

        class Store:
            def list_speech_integrations(self, tenant_id: str, reveal_secret: bool = False):
                return [untested]

        handler = SimpleNamespace(services=SimpleNamespace(system_config_store=Store()))
        selected = _resolve_fun_asr_speech_integration(
            handler, "tenant_demo", {"applicationModule": "realtime_voice_input"}, {}, "u_admin",
        )
        self.assertEqual(selected["id"], "speech_untested")

    def test_proxy_errors_are_stable_and_do_not_leak_exception_details(self) -> None:
        self.assertEqual(
            _public_fun_asr_error(ValueError("fun_asr_configuration_not_verified: secret detail")),
            "fun_asr_configuration_invalid",
        )
        self.assertEqual(
            _public_fun_asr_error(RuntimeError("private provider stack trace")),
            "fun_asr_proxy_failed",
        )


if __name__ == "__main__":
    unittest.main()
