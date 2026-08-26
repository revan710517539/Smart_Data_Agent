from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_no_personal_paths.py"
SPEC = importlib.util.spec_from_file_location("check_no_personal_paths", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PersonalPathGateTest(unittest.TestCase):
    def test_detects_macos_linux_and_windows_personal_homes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sample = root / "sample.txt"
            mac_path = "/" + "Users/alice/project"
            linux_path = "/" + "home/bob/project"
            windows_path = "C:" + "\\\\Users\\carol\\project"
            sample.write_text(
                f"{mac_path}\n{linux_path}\n{windows_path}\n",
                encoding="utf-8",
            )
            self.assertEqual(
                [item["code"] for item in MODULE.scan_paths(root, [sample])],
                ["personal_macos_home", "personal_linux_home", "personal_windows_home"],
            )

    def test_detects_absolute_data_crawler_checkout_paths(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sample = root / "sample.txt"
            first = "/opt/" + "palywright/examples/data-crawler/data"
            second = "/srv/ops/" + "playwright/examples/data-crawler/runtime-data"
            docker_mount = "/opt/" + "palywright/examples/data-crawler/data:/app/data:ro"
            quoted_exact = f'ROOT="{first}"'
            sample.write_text(f"{first}\n{second}\n{docker_mount}\n{quoted_exact}\n", encoding="utf-8")

            self.assertEqual(
                [item["code"] for item in MODULE.scan_paths(root, [sample])],
                ["personal_data_crawler_checkout"] * 4,
            )

    def test_gate_and_its_detection_fixture_do_not_self_report(self) -> None:
        self.assertEqual(MODULE.scan_paths(SCRIPT.parents[1], [SCRIPT, Path(__file__)]), [])

    def test_allows_portable_placeholders_and_relative_paths(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sample = root / "sample.txt"
            sample.write_text(
                "${HOME}/.hermes\n~/project\n/path/to/project\n<workspace>/artifact.png\n",
                encoding="utf-8",
            )
            self.assertEqual(MODULE.scan_paths(root, [sample]), [])

    def test_rejects_fixed_personal_loopback_service_but_allows_product_ports_and_tests(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = root / "backend" / "runtime.py"
            runtime.parent.mkdir()
            runtime.write_text(
                "API='http://127.0.0.1:8788'\nPERSONAL='http://127.0.0.1:8642'\n",
                encoding="utf-8",
            )
            test_file = root / "backend" / "tests" / "test_runtime.py"
            test_file.parent.mkdir()
            test_file.write_text("DUMMY='http://127.0.0.1:9999'\n", encoding="utf-8")

            violations = MODULE.scan_paths(root, [runtime, test_file])

            self.assertEqual([item["code"] for item in violations], ["personal_loopback_service"])
            self.assertEqual(violations[0]["port"], 8642)


if __name__ == "__main__":
    unittest.main()
