import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CLITests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "cvpr3d", *map(str, args)], capture_output=True, text=True)

    def test_demo_inspect_compare_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            asset = Path(temp) / "panel.glb"
            report = Path(temp) / "report.json"
            result = self.run_cli("demo", asset)
            self.assertEqual(result.returncode, 0, result.stderr)
            json.loads(result.stdout)
            original = asset.read_bytes()
            self.assertEqual(self.run_cli("demo", asset).returncode, 2)
            self.assertEqual(asset.read_bytes(), original)
            inspected = self.run_cli("inspect", asset, "--output", report)
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            saved = report.read_bytes()
            self.assertEqual(self.run_cli("inspect", asset, "--output", report).returncode, 2)
            self.assertEqual(report.read_bytes(), saved)
            comparison = self.run_cli("compare", asset, asset, "--require-preserved")
            self.assertEqual(comparison.returncode, 0, comparison.stderr)
            self.assertTrue(json.loads(comparison.stdout)["preserved"])

    def test_malformed_input_has_diagnostic_not_traceback(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.glb"
            path.write_bytes(b"invalid")
            result = self.run_cli("inspect", path)
            self.assertEqual(result.returncode, 2)
            self.assertIn("cvpr3d:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_missing_file_fails(self):
        result = self.run_cli("inspect", "nonexistent-example-file.glb")
        self.assertEqual(result.returncode, 2)

    def test_changed_manifest_returns_failure_and_json_report(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            path.write_text(json.dumps({"missing": {"bytes": 0, "sha256": "0" * 64}}))
            result = self.run_cli("verify-files", path)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(json.loads(result.stdout)["ok"])
