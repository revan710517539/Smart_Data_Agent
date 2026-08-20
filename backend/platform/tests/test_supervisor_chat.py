import json
import unittest
from unittest.mock import patch

from backend.platform.api.routes.supervisor import handle_supervisor_chat


class _Handler:
    def __init__(self, payload, model):
        self._payload = payload
        self._body = None
        self.headers = {}
        self.services = type("Services", (), {
            "system_config_store": object(),
        })()

    def _request_context(self, params=None):
        del params
        return type("Context", (), {"tenant_id": "tenant:华兴银行", "user_id": "u_super_admin"})()

    def _require_application_permission(self, context, action):
        del context, action

    def _read_json(self):
        return self._payload

    def _send_json(self, payload, *args, **kwargs):
        del args, kwargs
        self._body = payload


class SupervisorChatTest(unittest.TestCase):
    def test_supervisor_chat_uses_selected_model_and_returns_reply(self):
        handler = _Handler(
            {
                "question": "你能干什么？",
                "page_path": "/weekly-report",
                "institution": "华兴银行",
                "model_application_selection": {"integrationId": "model_gpt", "selectedModelName": "claude-sonnet-4-6"},
            },
            {"id": "model_gpt"},
        )
        with patch(
            "backend.platform.api.routes.supervisor.select_model_for_application",
            return_value={"id": "model_gpt", "name": "GPT等", "selectedModelName": "claude-sonnet-4-6"},
        ), patch(
            "backend.platform.api.routes.supervisor.call_model_text_completion",
            return_value={"status": "connected", "response_text": "我可以介绍当前页操作、查询指标口径。", "used_model": "claude-sonnet-4-6", "model_id": "model_gpt"},
        ) as completion:
            handle_supervisor_chat(handler)
        self.assertEqual(handler._body["status"], "connected")
        self.assertIn("指标口径", handler._body["reply"])
        self.assertEqual(handler._body["used_model"], "claude-sonnet-4-6")
        self.assertIn("你能干什么", completion.call_args.args[1])

    def test_supervisor_chat_requires_a_question(self):
        handler = _Handler({"question": "  "}, {"id": "model_gpt"})
        handle_supervisor_chat(handler)
        self.assertEqual(handler._body["error"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
