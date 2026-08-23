from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.platform.kernel.hermes_endpoint import HermesEndpointError, load_hermes_endpoint


class HermesEndpointTest(unittest.TestCase):
    def test_auto_and_empty_mode_stay_off(self) -> None:
        off = load_hermes_endpoint({"SMART_DATA_AGENT_ENV": "development"})
        self.assertEqual(off.mode, "off")
        auto = load_hermes_endpoint({"SMART_DATA_AGENT_ENV": "development", "SMART_DATA_AGENT_HERMES_MODE": "auto"})
        self.assertEqual(auto.mode, "off")

    def test_local_cli_uses_explicit_home_and_binary(self) -> None:
        endpoint = load_hermes_endpoint(
            {
                "SMART_DATA_AGENT_ENV": "development",
                "SMART_DATA_AGENT_HERMES_MODE": "cli",
                "SMART_DATA_AGENT_HERMES_BIN": "/usr/local/bin/hermes",
                "SMART_DATA_AGENT_HERMES_HOME": "~/.hermes",
            }
        )
        self.assertEqual(endpoint.mode, "cli")
        self.assertEqual(endpoint.binary, "/usr/local/bin/hermes")
        self.assertTrue(endpoint.home.endswith(".hermes"))

    def test_server_cli_requires_home(self) -> None:
        with self.assertRaisesRegex(HermesEndpointError, "HERMES_HOME"):
            load_hermes_endpoint(
                {
                    "SMART_DATA_AGENT_ENV": "production",
                    "SMART_DATA_AGENT_HERMES_MODE": "cli",
                    "SMART_DATA_AGENT_HERMES_BIN": "/usr/local/bin/hermes",
                }
            )

    def test_server_http_endpoint_is_swappable(self) -> None:
        local_http = load_hermes_endpoint(
            {
                "SMART_DATA_AGENT_ENV": "development",
                "SMART_DATA_AGENT_HERMES_MODE": "http",
                "SMART_DATA_AGENT_HERMES_ENDPOINT": "http://127.0.0.1:8642",
            }
        )
        self.assertEqual(local_http.mode, "http")
        self.assertEqual(local_http.endpoint, "http://127.0.0.1:8642")
        server_http = load_hermes_endpoint(
            {
                "SMART_DATA_AGENT_ENV": "production",
                "SMART_DATA_AGENT_HERMES_MODE": "http",
                "SMART_DATA_AGENT_HERMES_ENDPOINT": "https://hermes.internal.example/sda",
            }
        )
        self.assertEqual(server_http.endpoint, "https://hermes.internal.example/sda")
        with self.assertRaisesRegex(HermesEndpointError, "https"):
            load_hermes_endpoint(
                {
                    "SMART_DATA_AGENT_ENV": "production",
                    "SMART_DATA_AGENT_HERMES_MODE": "http",
                    "SMART_DATA_AGENT_HERMES_ENDPOINT": "http://hermes.internal.example",
                }
            )

    def test_cli_runner_passes_hermes_home_not_sda_secrets(self) -> None:
        from backend.platform.kernel.draft_provider import HermesDraftProvider

        captured: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["env"] = kwargs.get("env") or {}

            class Result:
                returncode = 0
                stdout = '{"title":"ok","trigger":{},"body":{"steps":["supersonic.query"]}}'
                stderr = ""

            return Result()

        with patch.dict(
            "os.environ",
            {"SMART_DATA_AGENT_DATABASE_URL": "mysql://secret", "PATH": "/bin"},
            clear=False,
        ):
            provider = HermesDraftProvider(
                load_hermes_endpoint(
                    {
                        "SMART_DATA_AGENT_ENV": "development",
                        "SMART_DATA_AGENT_HERMES_MODE": "cli",
                        "SMART_DATA_AGENT_HERMES_BIN": "/opt/hermes/bin/hermes",
                        "SMART_DATA_AGENT_HERMES_HOME": "/opt/hermes",
                    }
                ),
                runner=fake_run,
            )
            drafted = provider.draft({"episode": {"dataset_id": "loan_operation_mart"}})
        self.assertEqual(drafted["provider"], "hermes")
        self.assertEqual(captured["argv"][0], "/opt/hermes/bin/hermes")
        env = captured["env"]
        self.assertEqual(env["HERMES_HOME"], "/opt/hermes")
        self.assertNotIn("SMART_DATA_AGENT_DATABASE_URL", env)
        self.assertIn("--safe-mode", captured["argv"])


if __name__ == "__main__":
    unittest.main()
