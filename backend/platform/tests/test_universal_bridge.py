from __future__ import annotations

import http.client
import hashlib
import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.platform.api.server import create_server
from backend.platform.ingestion.topic_data import TopicDataStore
from backend.platform.integrations.bridge_connectors import BridgeConnectorRegistry


def _write_manifest(root: Path, tenant_id: str, directory: str, files: list[Path]) -> None:
    (root / "manifest.json").write_text(
        json.dumps({
            "schema_version": "smart-data-crawler-manifest/v1",
            "generated_at": "2026-08-28T00:00:00+08:00",
            "tenants": [{
                "tenant_id": tenant_id,
                "tenant_ids": [tenant_id],
                "institution_id": tenant_id.removeprefix("tenant:"),
                "institution_directory": directory,
                "schema_version": "data-crawler-csv/v1",
                "files": [{
                    "path": path.relative_to(root / directory).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                } for path in files],
            }],
        }, ensure_ascii=False),
        encoding="utf-8",
    )


def _connector(connector_id: str, base_url: str) -> dict:
    return {
        "id": connector_id,
        "label": f"{connector_id} system",
        "description": "测试系统",
        "aliases": [f"{connector_id} alias"],
        "adapter": "http_json",
        "base_url": base_url,
        "auth": {"type": "none"},
        "allowed_channels": ["workbuddy", "codex", "qwork"],
        "modules": {
            "analysis_sync": {"path": "/analysis"},
            "configuration": {"actions": {"canvas.create": {"path": "/configuration/canvas-create"}}},
            "read": {"path": "/read"},
            "learning": {"path": "/learning"},
        },
    }


def _write_registry(path: Path, connectors: list[dict]) -> None:
    path.write_text(
        json.dumps({"schema_version": "bridge_connector_registry_v1", "connectors": connectors}, ensure_ascii=False),
        encoding="utf-8",
    )


def _request(
    port: int,
    path: str,
    payload: dict | None,
    *,
    token: str = "codex-token",
    channel: str = "codex",
) -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Authorization": f"Bearer {token}", "X-Bridge-Channel": channel}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    connection.request(
        "POST" if payload is not None else "GET",
        path,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None,
        headers=headers,
    )
    response = connection.getresponse()
    body = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, body


class _ConnectorHandler(BaseHTTPRequestHandler):
    calls: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.calls.append({"path": self.path, "payload": payload, "headers": dict(self.headers)})
        body = json.dumps({"accepted": True, "path": self.path, "operation_id": payload.get("operation_id")}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


class UniversalBridgeRegistryTest(unittest.TestCase):
    def test_registry_requires_four_modules_and_never_exposes_adapter_secrets(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "connectors.json"
            _write_registry(path, [])
            manifest = BridgeConnectorRegistry(path).public_manifest("codex")
            self.assertEqual(manifest["modules"], ["analysis_sync", "configuration", "read", "learning"])
            self.assertFalse(manifest["client_reinstall_required_for_new_system"])
            self.assertEqual([item["id"] for item in manifest["systems"]], ["sda"])

            invalid = _connector("canvas", "http://127.0.0.1:1")
            invalid["modules"].pop("learning")
            _write_registry(path, [invalid])
            with self.assertRaisesRegex(ValueError, "four_modules_required"):
                BridgeConnectorRegistry(path).public_manifest("codex")

            inline_secret = _connector("canvas", "http://127.0.0.1:1")
            inline_secret["auth"] = {"type": "bearer_env", "environment": "CANVAS_TOKEN", "token": "must-not-be-here"}
            _write_registry(path, [inline_secret])
            with self.assertRaisesRegex(ValueError, "inline_secret_forbidden"):
                BridgeConnectorRegistry(path).public_manifest("codex")

    def test_registry_is_reread_so_backend_additions_need_no_client_reinstall(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "connectors.json"
            _write_registry(path, [_connector("canvas", "http://127.0.0.1:1")])
            registry = BridgeConnectorRegistry(path)
            self.assertEqual({item["id"] for item in registry.public_manifest("qwork")["systems"]}, {"sda", "canvas"})
            _write_registry(path, [
                _connector("canvas", "http://127.0.0.1:1"),
                _connector("crm", "http://127.0.0.1:2"),
            ])
            self.assertEqual({item["id"] for item in registry.public_manifest("qwork")["systems"]}, {"sda", "canvas", "crm"})


class UniversalBridgeHTTPTest(unittest.TestCase):
    def test_external_connector_all_four_modules_and_dynamic_discovery(self) -> None:
        _ConnectorHandler.calls = []
        connector_server = ThreadingHTTPServer(("127.0.0.1", 0), _ConnectorHandler)
        connector_thread = threading.Thread(target=connector_server.serve_forever, daemon=True)
        connector_thread.start()
        bindings = json.dumps({"bindings": [{
            "id": "codex-local",
            "token": "codex-token",
            "channel": "codex",
            "tenant_id": "tenant_demo",
            "user_id": "u_super_admin",
        }]})
        with TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "connectors.json"
            base_url = f"http://127.0.0.1:{connector_server.server_address[1]}"
            _write_registry(registry_path, [_connector("canvas", base_url)])
            environment = {
                "SMART_DATA_AGENT_REPORT_INGRESS_BINDINGS_JSON": bindings,
                "SMART_DATA_AGENT_BRIDGE_CONNECTORS_FILE": str(registry_path),
            }
            with patch.dict(os.environ, environment, clear=False):
                server = create_server("127.0.0.1", 0, f"{tmpdir}/platform.sqlite")
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    port = server.server_address[1]
                    status, manifest = _request(port, "/api/integrations/bridge/manifest", None)
                    self.assertEqual(status, 200)
                    self.assertEqual({item["id"] for item in manifest["systems"]}, {"sda", "canvas"})
                    self.assertFalse(manifest["client_reinstall_required_for_new_system"])

                    requests = [
                        ("/api/integrations/bridge/context", {"system_id": "canvas"}),
                        ("/api/integrations/bridge/read", {"system_id": "canvas", "resource": "policy", "input": {"resource": "policy"}}),
                        ("/api/integrations/bridge/action", {"system_id": "canvas", "action": "canvas.create", "operation_id": "op-1", "input": {"title": "经营画布"}}),
                        ("/api/integrations/bridge/sync", {"system_id": "canvas", "operation_id": "op-1", "input": {"summary": "分析结果"}}),
                        ("/api/integrations/bridge/evidence", {"system_id": "canvas", "operation_id": "op-1", "input": {"summary": "操作证据"}}),
                    ]
                    for path, payload in requests:
                        response_status, response = _request(port, path, payload)
                        self.assertEqual(response_status, 200, response)
                        self.assertEqual(response["system_id"], "canvas")
                    self.assertEqual([call["path"] for call in _ConnectorHandler.calls], [
                        "/read", "/read", "/configuration/canvas-create", "/analysis", "/learning",
                    ])
                    for call in _ConnectorHandler.calls:
                        identity = call["payload"]["identity"]
                        self.assertEqual(identity["tenant_id"], "tenant_demo")
                        self.assertEqual(identity["user_id"], "u_super_admin")
                        self.assertEqual(identity["channel"], "codex")

                    denied_status, _ = _request(port, "/api/integrations/bridge/action", {
                        "system_id": "canvas", "action": "canvas.delete", "operation_id": "op-2", "input": {},
                    })
                    self.assertEqual(denied_status, 403)
                    missing_operation_status, _ = _request(port, "/api/integrations/bridge/sync", {
                        "system_id": "canvas", "input": {},
                    })
                    self.assertEqual(missing_operation_status, 400)
                    identity_override_status, _ = _request(port, "/api/integrations/bridge/action", {
                        "system_id": "canvas", "action": "canvas.create", "operation_id": "op-3",
                        "input": {"tenant_id": "tenant_other", "title": "越权画布"},
                    })
                    self.assertEqual(identity_override_status, 400)
                    transcript_status, _ = _request(port, "/api/integrations/bridge/evidence", {
                        "system_id": "canvas", "operation_id": "op-4", "input": {"transcript": "不应外发"},
                    })
                    self.assertEqual(transcript_status, 400)
                    wrong_channel_status, _ = _request(port, "/api/integrations/bridge/manifest", None, channel="qwork")
                    self.assertEqual(wrong_channel_status, 403)

                    _write_registry(registry_path, [
                        _connector("canvas", base_url),
                        _connector("crm", base_url),
                    ])
                    updated_status, updated = _request(port, "/api/integrations/bridge/manifest", None)
                    self.assertEqual(updated_status, 200)
                    self.assertEqual({item["id"] for item in updated["systems"]}, {"sda", "canvas", "crm"})

                    cli = Path(__file__).resolve().parents[3] / "integrations/workbuddy-smart-data-report/bin/sda_report.py"
                    config = Path(tmpdir) / "report-cli.json"
                    config.write_text(json.dumps({"endpoint": f"http://127.0.0.1:{port}"}), encoding="utf-8")
                    cli_input = Path(tmpdir) / "cli-input.json"
                    cli_input.write_text(json.dumps({"title": "CLI 画布", "summary": "CLI 结果"}, ensure_ascii=False), encoding="utf-8")
                    cli_environment = os.environ.copy()
                    cli_environment["SMART_DATA_AGENT_REPORT_TOKEN"] = "codex-token"

                    def run_cli(*arguments: str) -> dict:
                        completed = subprocess.run(
                            [sys.executable, str(cli), "bridge", "--channel", "codex", *arguments, "--config", str(config), "--json"],
                            check=True,
                            text=True,
                            capture_output=True,
                            env=cli_environment,
                        )
                        return json.loads(completed.stdout)

                    cli_manifest = run_cli("systems")
                    self.assertEqual({item["id"] for item in cli_manifest["systems"]}, {"sda", "canvas", "crm"})
                    self.assertEqual(run_cli("context", "--system", "canvas")["system_id"], "canvas")
                    self.assertEqual(run_cli("read", "--system", "canvas", "--resource", "policy", "--input", str(cli_input))["module"], "read")
                    self.assertEqual(run_cli("action", "--system", "canvas", "--action", "canvas.create", "--operation-id", "cli-op-1", "--input", str(cli_input))["module"], "configuration")
                    self.assertEqual(run_cli("sync", "--system", "canvas", "--operation-id", "cli-op-1", "--input", str(cli_input))["module"], "analysis_sync")
                    self.assertEqual(run_cli("evidence", "--system", "canvas", "--operation-id", "cli-op-1", "--input", str(cli_input))["module"], "learning")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)
        connector_server.shutdown()
        connector_server.server_close()
        connector_thread.join(timeout=5)

    def test_builtin_sda_read_sync_configure_and_learning_are_bound_and_review_only(self) -> None:
        bindings = json.dumps({"bindings": [{
            "id": "codex-sda",
            "token": "codex-token",
            "channel": "codex",
            "tenant_id": "tenant_demo",
            "user_id": "u_super_admin",
        }]})
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "csv"
            tenant_dir = root / "tenant_demo"
            tenant_dir.mkdir(parents=True)
            authorized = tenant_dir / "authorized.csv"
            authorized.write_text("机构,金额\nA,10\n", encoding="utf-8")
            _write_manifest(root, "tenant_demo", "tenant_demo", [authorized])
            environment = {
                "SMART_DATA_AGENT_REPORT_INGRESS_BINDINGS_JSON": bindings,
                "SMART_DATA_AGENT_DATA_CRAWLER_ROOT": str(root),
                "SMART_DATA_AGENT_BRIDGE_CONNECTORS_FILE": "",
            }
            with patch.dict(os.environ, environment, clear=False):
                server = create_server("127.0.0.1", 0, f"{tmpdir}/platform.sqlite")
                server.services.topic_data_store = TopicDataStore(f"{tmpdir}/topic-data")
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    catalog = server.services.data_acquisition_service.csv_source.for_tenant("tenant_demo")
                    catalog.prime_catalog()
                    table = catalog.table_assets()[0]
                    server.services.data_asset_store.set_raw_table_external_reference(
                        "tenant_demo", table["sourceKey"], "shared", table["schemaFingerprint"], "u_super_admin",
                    )
                    port = server.server_address[1]
                    context_status, context = _request(port, "/api/integrations/bridge/context", {"system_id": "sda"})
                    self.assertEqual(context_status, 200)
                    self.assertEqual(context["result"]["raw_tables"][0]["sourceKey"], table["sourceKey"])
                    read_status, read = _request(port, "/api/integrations/bridge/read", {
                        "system_id": "sda",
                        "resource": "raw_table.rows",
                        "input": {"source_key": table["sourceKey"], "columns": ["机构", "金额"], "limit": 1},
                    })
                    self.assertEqual(read_status, 200)
                    self.assertEqual(read["result"]["rows"], [{"机构": "A", "金额": "10"}])

                    action_status, action = _request(port, "/api/integrations/bridge/action", {
                        "system_id": "sda",
                        "action": "analysis_shortcut.upsert",
                        "operation_id": "shortcut-op-1",
                        "input": {"id": "shortcut-bridge-test", "title": "Bridge 快捷分析", "query": "分析金额"},
                    })
                    self.assertEqual(action_status, 200, action)
                    self.assertEqual(action["result"]["item"]["ownerUserId"], "u_super_admin")

                    sync_status, sync = _request(port, "/api/integrations/bridge/sync", {
                        "system_id": "sda",
                        "operation_id": "analysis-op-1",
                        "input": {
                            "source": {"channel": "codex", "run_id": "analysis-op-1", "report_id": "bridge-report"},
                            "report": {"title": "Bridge 分析", "summary": "A 金额为 10", "rows": [{"机构": "A", "金额": 10}]},
                        },
                    })
                    self.assertEqual(sync_status, 200, sync)
                    self.assertEqual(sync["result"]["channel"], "codex")

                    evidence_payload = {
                        "system_id": "sda",
                        "operation_id": "shortcut-op-1",
                        "input": {
                            "run_id": "shortcut-op-1",
                            "action": "analysis_shortcut.upsert",
                            "title": "创建快捷分析",
                            "summary": "创建了当前用户的快捷分析入口。",
                            "methodology": "按白名单字段配置。",
                            "logic_steps": ["校验权限", "写入配置", "回读结果"],
                            "findings": ["配置成功"],
                        },
                    }
                    evidence_status, evidence = _request(port, "/api/integrations/bridge/evidence", evidence_payload)
                    self.assertEqual(evidence_status, 200, evidence)
                    self.assertTrue(evidence["result"]["accepted"])
                    self.assertTrue(evidence["result"]["review_required"])
                    self.assertFalse(evidence["result"]["idempotent_replay"])
                    candidate_id = evidence["result"]["memory_candidate_id"]
                    candidate = server.services.memory_service.get("tenant_demo", candidate_id)
                    self.assertEqual(candidate["status"], "candidate")
                    self.assertEqual(candidate["subject_id"], "u_super_admin")
                    replay_status, replay = _request(port, "/api/integrations/bridge/evidence", evidence_payload)
                    self.assertEqual(replay_status, 200)
                    self.assertTrue(replay["result"]["idempotent_replay"])
                    conflict_payload = json.loads(json.dumps(evidence_payload, ensure_ascii=False))
                    conflict_payload["input"]["summary"] = "同一个 operation ID 不允许绑定另一份证据。"
                    conflict_status, _ = _request(port, "/api/integrations/bridge/evidence", conflict_payload)
                    self.assertEqual(conflict_status, 400)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
