from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.platform.api.routes.bridge_distribution import (
    BRIDGE_DISTRIBUTION_VERSION,
    build_bridge_distribution_bundle,
)
from backend.platform.api.router import API_ROUTE_REGISTRY


ROOT = Path(__file__).resolve().parents[3]
DOCS = {
    ("workbuddy", "macos"): ROOT / "docs/integrations/workbuddy-smart-data-agent-install-macos.md",
    ("workbuddy", "windows"): ROOT / "docs/integrations/workbuddy-smart-data-agent-install-windows.md",
    ("codex", "macos"): ROOT / "docs/integrations/codex-smart-data-agent-install-macos.md",
    ("codex", "windows"): ROOT / "docs/integrations/codex-smart-data-agent-install-windows.md",
    ("qwork", "macos"): ROOT / "docs/integrations/qwork-smart-data-agent-install-macos.md",
    ("qwork", "windows"): ROOT / "docs/integrations/qwork-smart-data-agent-install-windows.md",
}


class BridgeOnboardingContractTest(unittest.TestCase):
    def test_six_guides_have_one_paste_once_install_four_module_contract(self) -> None:
        self.assertEqual(len(DOCS), 6)
        for (channel, platform), path in DOCS.items():
            with self.subTest(channel=channel, platform=platform):
                body = path.read_text(encoding="utf-8")
                self.assertIn("直接粘贴", body)
                self.assertIn("Universal Bridge", body)
                self.assertTrue("安装一次" in body or "只做一次" in body)
                self.assertIn("允许连接", body)
                self.assertTrue("不要索取令牌" in body or "不得要求我复制令牌" in body)
                self.assertIn("systems", body)
                self.assertIn("context --system sda", body)
                self.assertIn("同步", body)
                self.assertTrue("配置动作" in body or "后台配置" in body)
                self.assertIn("授权数据", body)
                self.assertIn("证据", body)
                self.assertIn("记忆", body)
                self.assertIn("Skill", body)
                self.assertIn("新增系统", body)
                self.assertIn("无需重装", body)
                self.assertIn("不得上传完整对话", body)
                self.assertTrue("不得选择默认/第一项" in body or "不得使用默认系统或第一项" in body)
                self.assertIn("context", body)
                self.assertIn("https://SDA_SERVER", body)
                self.assertIn("distribution/manifest", body)
                self.assertIn("package.sha256", body)
                self.assertNotIn("/Users/revan", body)
                self.assertNotIn("127.0.0.1:8788", body)
                self.assertTrue("403/404" in body or "403、404" in body)
                self.assertIn(channel, body.lower())
                self.assertIn("powershell" if platform == "windows" else "```sh", body.lower())

    def test_distribution_bundle_is_deterministic_allowlisted_and_hash_addressed(self) -> None:
        bundle, digest = build_bridge_distribution_bundle()
        build_bridge_distribution_bundle.cache_clear()
        rebuilt, rebuilt_digest = build_bridge_distribution_bundle()
        self.assertEqual(bundle, rebuilt)
        self.assertEqual(digest, rebuilt_digest)
        self.assertEqual(hashlib.sha256(bundle).hexdigest(), digest)
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            names = archive.namelist()
            self.assertIn("MANIFEST.json", names)
            self.assertIn("integrations/smart-data-agent-bridge/install-macos.sh", names)
            self.assertIn("integrations/smart-data-agent-bridge/install-windows.ps1", names)
            self.assertIn("integrations/workbuddy-smart-data-report/bin/sda_report.py", names)
            self.assertIn("integrations/codex-smart-data-agent-bridge/smart-data-agent-bridge/SKILL.md", names)
            self.assertIn("integrations/qwork-smart-data-agent-bridge/smart-data-agent-bridge/SKILL.md", names)
            self.assertFalse(any(name.startswith("docs/") or "__pycache__" in name for name in names))
            manifest = json.loads(archive.read("MANIFEST.json"))
            self.assertEqual(manifest["version"], BRIDGE_DISTRIBUTION_VERSION)
            for item in manifest["files"]:
                self.assertEqual(hashlib.sha256(archive.read(item["path"])).hexdigest(), item["sha256"])
        for path in (
            "/api/integrations/bridge/distribution/manifest",
            "/api/integrations/bridge/distribution/package",
            "/api/integrations/bridge/distribution/package.sha256",
        ):
            self.assertTrue(API_ROUTE_REGISTRY.has_route("GET", path))

    def test_skills_encode_dynamic_discovery_four_modules_and_review_only_evidence(self) -> None:
        for channel in ("codex", "qwork"):
            body = (ROOT / f"integrations/{channel}-smart-data-agent-bridge/smart-data-agent-bridge/SKILL.md").read_text(encoding="utf-8")
            self.assertIn(f"--channel {channel}", body)
            for command in ("systems", "context", "read", "sync", "action", "evidence"):
                self.assertIn(command, body)
            self.assertIn("operation", body.lower())
            self.assertTrue("reinstall" in body.lower() or "重装" in body)
            self.assertIn("自动" if channel == "qwork" else "automatically", body)
            self.assertTrue("review" in body.lower() or "待复核" in body)
            self.assertNotIn("127.0.0.1", body)
        hook = (ROOT / "integrations/workbuddy-smart-data-report/hooks/hooks.json").read_text(encoding="utf-8")
        self.assertIn("SDA bridge --channel workbuddy read", hook)
        self.assertIn("action", hook)
        self.assertIn("sync", hook)
        self.assertIn("evidence", hook)
        self.assertIn("same exact system and operation ID", hook)

    def test_macos_installer_projects_codex_and_qwork_skills(self) -> None:
        source_installer = ROOT / "integrations/smart-data-agent-bridge/install-macos.sh"
        subprocess.run(["sh", "-n", str(source_installer)], check=True)
        with TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir) / "package"
            package_root.mkdir()
            bundle, _ = build_bridge_distribution_bundle()
            with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
                archive.extractall(package_root)
            installer = package_root / "integrations/smart-data-agent-bridge/install-macos.sh"
            home = Path(tmpdir) / "home"
            home.mkdir()
            environment = os.environ.copy()
            environment.update({
                "HOME": str(home),
                "USER": "bridge-test-user",
                "CODEX_HOME": str(home / ".codex"),
                "DEEPBANK_HOME": str(home / ".deepbank"),
            })
            for channel in ("codex", "qwork"):
                completed = subprocess.run(
                    [
                        "sh", str(installer), "--channel", channel,
                        "--bundle-root", str(package_root),
                        "--server-url", "http://127.0.0.1:8788",
                        "--allow-local-dev", "--skip-server-check", "--skip-token-check",
                    ],
                    check=True,
                    text=True,
                    capture_output=True,
                    env=environment,
                )
                self.assertIn(f"channel={channel}", completed.stdout)
            self.assertTrue((home / ".codex/skills/smart-data-agent-bridge/SKILL.md").is_file())
            qwork_agents = home / ".deepbank/.agents/skills/smart-data-agent-bridge/SKILL.md"
            qwork_claude = home / ".deepbank/.claude/skills/smart-data-agent-bridge/SKILL.md"
            self.assertEqual(qwork_agents.read_bytes(), qwork_claude.read_bytes())
            config = json.loads((home / ".config/smart-data-agent/report-cli.json").read_text(encoding="utf-8"))
            self.assertEqual(config["endpoint"], "http://127.0.0.1:8788")
            self.assertEqual(config["app_url"], "http://127.0.0.1:8788")
            help_result = subprocess.run(
                [str(home / ".local/bin/SDA"), "bridge", "--help"],
                check=True,
                text=True,
                capture_output=True,
                env=environment,
            )
            self.assertIn("workbuddy", help_result.stdout)
            self.assertIn("codex", help_result.stdout)
            self.assertIn("qwork", help_result.stdout)

    def test_installers_preserve_platform_secret_boundaries(self) -> None:
        workbuddy_mac = ROOT / "integrations/workbuddy-smart-data-report/install-macos.sh"
        subprocess.run(["sh", "-n", str(workbuddy_mac)], check=True)
        windows = (ROOT / "integrations/smart-data-agent-bridge/install-windows.ps1").read_text(encoding="utf-8")
        self.assertIn("connect --channel $Channel", windows)
        self.assertIn("浏览器授权", windows)
        self.assertNotIn("Read-Host", windows)
        self.assertIn("[Parameter(Mandatory = $true)]", windows)
        self.assertIn("sda_bridge_distribution_v1", windows)
        self.assertNotIn("'http://127.0.0.1:8788'", windows)
        self.assertIn("bridge --channel $Channel systems", windows)
        self.assertIn("context --system sda", windows)
        self.assertNotIn("token = 'test", windows.lower())

    def test_operator_binding_guide_covers_all_channels_with_distinct_bindings(self) -> None:
        body = (ROOT / "docs/integrations/external-report-cli.md").read_text(encoding="utf-8")
        for channel in ("workbuddy", "codex", "qwork"):
            self.assertIn(f'"channel": "{channel}"', body)
            self.assertIn(f'"id": "{channel}-revan"', body)
        self.assertIn("三个渠道使用不同令牌", body)
        self.assertIn("不能交叉复用凭据", body)

    def test_data_asset_ui_names_all_bridge_consumers(self) -> None:
        body = (ROOT / "src/app/components/DataAssets.tsx").read_text(encoding="utf-8")
        self.assertIn("WorkBuddy、Codex、QWork Bridge", body)

    def test_browser_approval_route_uses_current_platform_tenant(self) -> None:
        component = (ROOT / "src/app/components/BridgeAuthorization.tsx").read_text(encoding="utf-8")
        service = (ROOT / "src/app/services/bridgeApi.ts").read_text(encoding="utf-8")
        routes = (ROOT / "src/app/routes.ts").read_text(encoding="utf-8")
        self.assertIn("selectedInstitution", component)
        self.assertIn("允许连接", component)
        self.assertIn("approveBridgeEnrollment", component)
        self.assertIn("/api/integrations/bridge/enrollment/approve", service)
        self.assertIn('path: "bridge-authorize"', routes)


if __name__ == "__main__":
    unittest.main()
