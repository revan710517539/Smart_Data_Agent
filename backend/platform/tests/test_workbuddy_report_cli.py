from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch


CLI_PATH = Path(__file__).resolve().parents[3] / "integrations" / "workbuddy-smart-data-report" / "bin" / "sda_report.py"


def bridge_manifest(channel: str = "codex") -> dict:
    return {
        "schema_version": "bridge_manifest_v1",
        "contract_version": "1.0",
        "channel": channel,
        "modules": ["analysis_sync", "configuration", "read", "learning"],
        "systems": [{"id": "sda", "label": "Smart Data Agent"}],
    }


def load_cli_module():
    spec = importlib.util.spec_from_file_location("workbuddy_report_cli", CLI_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("workbuddy_report_cli_load_failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WorkBuddyReportCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = load_cli_module()

    def test_plugin_cli_is_self_contained(self) -> None:
        plugin_root = CLI_PATH.parents[1]
        self.assertTrue((plugin_root / "bin" / "SDA").is_file())
        self.assertTrue((plugin_root / "bin" / "SDA.cmd").is_file())
        self.assertNotIn("../../scripts/SDA", (plugin_root / "bin" / "SDA").read_text(encoding="utf-8"))
        launcher = Path(__file__).resolve().parents[3] / "scripts" / "SDA"
        self.assertIn("integrations/workbuddy-smart-data-report/bin/sda_report.py", launcher.read_text(encoding="utf-8"))

    def test_windows_uses_appdata_for_non_secret_config_and_dpapi_token(self) -> None:
        with patch.object(self.cli.sys, "platform", "win32"), patch.dict(os.environ, {"APPDATA": r"C:\\Users\\Ada\\AppData\\Roaming"}, clear=False):
            self.assertEqual(
                self.cli._default_config_path(),
                Path(r"C:\\Users\\Ada\\AppData\\Roaming") / "smart-data-agent" / "report-cli.json",
            )
            self.assertEqual(
                self.cli._windows_token_path(),
                Path(r"C:\\Users\\Ada\\AppData\\Roaming") / "smart-data-agent" / "report-cli.token",
            )
            self.assertEqual(
                self.cli._windows_token_path("smart-data-agent-bridge-codex"),
                Path(r"C:\\Users\\Ada\\AppData\\Roaming") / "smart-data-agent" / "report-cli-codex.token",
            )

    def test_config_accepts_windows_utf8_bom(self) -> None:
        with TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "report-cli.json"
            config.write_bytes(b"\xef\xbb\xbf{\"endpoint\":\"https://sda.example.com\"}")
            self.assertEqual(
                self.cli._endpoint(None, config),
                "https://sda.example.com/api/integrations/reports",
            )
            self.assertEqual(
                self.cli._api_endpoint(None, config, "/api/integrations/workbuddy/context"),
                "https://sda.example.com/api/integrations/workbuddy/context",
            )

    def test_bridge_routes_codex_qwork_and_keeps_workbuddy_alias(self) -> None:
        with TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "report-cli.json"
            config.write_text('{"endpoint":"https://sda.example.com"}', encoding="utf-8")
            evidence = Path(tmpdir) / "evidence.json"
            evidence.write_text(json.dumps({
                "references": [{"source_key": "source-1", "schema_fingerprint": "schema-1"}],
                "run_id": "run-1",
                "summary": "摘要",
                "methodology": "方法",
            }, ensure_ascii=False), encoding="utf-8")
            calls: list[tuple[str, str]] = []

            def fake_request(endpoint, token, payload, timeout, *, method="POST", channel="external"):
                calls.append((endpoint, channel))
                return {"accepted": True}

            with patch.dict(os.environ, {"SMART_DATA_AGENT_REPORT_TOKEN": "test-token"}, clear=False), patch.object(self.cli, "_request_json", side_effect=fake_request):
                self.assertEqual(self.cli.main(["bridge", "--channel", "codex", "context", "--config", str(config), "--json"]), 0)
                self.assertEqual(self.cli.main(["bridge", "--channel", "qwork", "evidence", "--config", str(config), "--input", str(evidence), "--json"]), 0)
                self.assertEqual(self.cli.main(["workbuddy", "context", "--config", str(config), "--json"]), 0)
            self.assertEqual(calls, [
                ("https://sda.example.com/api/integrations/codex/context", "codex"),
                ("https://sda.example.com/api/integrations/qwork/evidence", "qwork"),
                ("https://sda.example.com/api/integrations/workbuddy/context", "workbuddy"),
            ])

    def test_universal_bridge_routes_all_four_modules_to_exact_system(self) -> None:
        with TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "report-cli.json"
            config.write_text('{"endpoint":"https://bridge.example.com"}', encoding="utf-8")
            input_file = Path(tmpdir) / "input.json"
            input_file.write_text(json.dumps({"title": "测试", "run_id": "op-1"}, ensure_ascii=False), encoding="utf-8")
            calls: list[tuple[str, dict | None, str, str]] = []

            def fake_request(endpoint, token, payload, timeout, *, method="POST", channel="external"):
                calls.append((endpoint, payload, method, channel))
                return bridge_manifest(channel) if endpoint.endswith("/manifest") else {"accepted": True}

            with patch.dict(os.environ, {"SMART_DATA_AGENT_REPORT_TOKEN": "test-token"}, clear=False), patch.object(self.cli, "_request_json", side_effect=fake_request):
                self.assertEqual(self.cli.main(["bridge", "--channel", "codex", "systems", "--config", str(config), "--json"]), 0)
                self.assertEqual(self.cli.main(["bridge", "--channel", "codex", "context", "--system", "canvas", "--config", str(config), "--json"]), 0)
                self.assertEqual(self.cli.main(["bridge", "--channel", "codex", "read", "--system", "canvas", "--resource", "policy", "--input", str(input_file), "--config", str(config), "--json"]), 0)
                self.assertEqual(self.cli.main(["bridge", "--channel", "codex", "action", "--system", "canvas", "--action", "canvas.create", "--operation-id", "op-1", "--input", str(input_file), "--config", str(config), "--json"]), 0)
                self.assertEqual(self.cli.main(["bridge", "--channel", "codex", "sync", "--system", "canvas", "--operation-id", "op-1", "--input", str(input_file), "--config", str(config), "--json"]), 0)
                self.assertEqual(self.cli.main(["bridge", "--channel", "codex", "evidence", "--system", "canvas", "--operation-id", "op-1", "--input", str(input_file), "--config", str(config), "--json"]), 0)

            self.assertEqual([call[0] for call in calls], [
                "https://bridge.example.com/api/integrations/bridge/manifest",
                "https://bridge.example.com/api/integrations/bridge/context",
                "https://bridge.example.com/api/integrations/bridge/read",
                "https://bridge.example.com/api/integrations/bridge/action",
                "https://bridge.example.com/api/integrations/bridge/sync",
                "https://bridge.example.com/api/integrations/bridge/evidence",
            ])
            self.assertEqual(calls[0][2], "GET")
            self.assertEqual(calls[1][1], {"system_id": "canvas"})
            self.assertEqual(calls[2][1]["resource"], "policy")
            self.assertEqual(calls[3][1]["action"], "canvas.create")
            self.assertEqual(calls[3][1]["operation_id"], "op-1")
            self.assertEqual(calls[4][1]["system_id"], "canvas")
            self.assertEqual(calls[5][1]["operation_id"], "op-1")
            self.assertTrue(all(call[3] == "codex" for call in calls))

    def test_multiple_sources_require_matching_evidence_references(self) -> None:
        evidence = {"references": [
            {"source_key": "source-1", "schema_fingerprint": "schema-1"},
            {"source_key": "source-2", "schema_fingerprint": "schema-2"},
        ]}
        self.cli._bind_evidence_sources(evidence, ["source-1", "source-2"])
        with self.assertRaisesRegex(ValueError, "source_keys_do_not_match"):
            self.cli._bind_evidence_sources(evidence, ["source-2", "source-1"])

    def test_token_prefers_environment_before_platform_secret_store(self) -> None:
        with patch.dict(os.environ, {"SMART_DATA_AGENT_REPORT_TOKEN": "non-secret-test-value"}, clear=False), patch.object(self.cli.sys, "platform", "win32"), patch.object(self.cli, "_windows_dpapi_token", return_value="should-not-be-read") as reader:
            self.assertEqual(self.cli._token("SMART_DATA_AGENT_REPORT_TOKEN", "ignored"), "non-secret-test-value")
            reader.assert_not_called()

    def test_connect_uses_browser_device_authorization_and_stores_token_once(self) -> None:
        with TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "report-cli.json"
            config.write_text('{"endpoint":"https://sda.example.com"}', encoding="utf-8")
            responses = [
                {
                    "device_code": "device-code",
                    "verification_uri_complete": "/bridge-authorize?user_code=ABCD-EFGH",
                    "interval": 1,
                },
                {"status": "authorized", "token": "one-time-token", "binding": {"binding_id": "bridge_codex_1", "channel": "codex"}},
                bridge_manifest("codex"),
            ]
            with patch.object(self.cli, "_request_json", side_effect=responses) as requester, patch.object(self.cli, "_store_platform_token") as store_token:
                result = self.cli.main([
                    "connect", "--channel", "codex", "--config", str(config),
                    "--token-keychain-service", "smart-data-agent-bridge-codex", "--no-open", "--json",
                ])
            self.assertEqual(result, 0)
            store_token.assert_called_once_with("one-time-token", "smart-data-agent-bridge-codex")
            self.assertEqual(requester.call_count, 3)
            self.assertNotIn("token", requester.call_args_list[-1].args[2] or {})

    def test_remote_http_endpoint_and_manifest_contract_drift_fail_closed(self) -> None:
        with TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "report-cli.json"
            config.write_text('{"endpoint":"http://sda.example.com"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "endpoint_https_required"):
                self.cli._base_endpoint(None, config)
        with self.assertRaisesRegex(ValueError, "bridge_contract_version_unsupported"):
            self.cli._validate_bridge_manifest({**bridge_manifest(), "contract_version": "2.0"}, "codex")
        with self.assertRaisesRegex(ValueError, "bridge_manifest_channel_mismatch"):
            self.cli._validate_bridge_manifest(bridge_manifest("qwork"), "codex")

    def test_local_api_endpoint_derives_local_frontend_authorization_url(self) -> None:
        with TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "report-cli.json"
            config.write_text('{"endpoint":"http://127.0.0.1:8788"}', encoding="utf-8")
            self.assertEqual(self.cli._app_endpoint(None, config, "http://127.0.0.1:8788"), "http://127.0.0.1:5174")

    def test_windows_connect_storage_writes_only_dpapi_ciphertext(self) -> None:
        with TemporaryDirectory() as tmpdir, patch.object(self.cli.sys, "platform", "win32"), patch.dict(os.environ, {"APPDATA": tmpdir}, clear=False), patch.object(
            self.cli.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="dpapi-ciphertext\n", stderr=""),
        ) as runner:
            self.cli._store_platform_token("plain-token", "smart-data-agent-bridge-qwork")
            token_path = Path(tmpdir) / "smart-data-agent" / "report-cli-qwork.token"
            self.assertEqual(token_path.read_text(encoding="utf-8"), "dpapi-ciphertext")
            self.assertEqual(runner.call_args.kwargs["input"], "plain-token")
            self.assertNotIn("plain-token", runner.call_args.args[0])

    def test_macos_connect_storage_keeps_token_out_of_process_arguments(self) -> None:
        with patch.object(self.cli.sys, "platform", "darwin"), patch.object(
            self.cli.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ) as runner:
            self.cli._store_platform_token("plain-token", "smart-data-agent-bridge-codex")
            self.assertNotIn("plain-token", runner.call_args.args[0])
            self.assertEqual(runner.call_args.kwargs["input"], "plain-token\nplain-token\n")


if __name__ == "__main__":
    unittest.main()
