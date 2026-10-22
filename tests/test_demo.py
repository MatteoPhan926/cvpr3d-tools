"""The demo must be deterministic, self-contained, and refuse overwriting."""

from pathlib import Path
import tempfile
import unittest

from cvpr3d.demo import generate_demo
from cvpr3d.glb import compare_glbs, inspect_glb


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_deterministic_output_and_declared_inventory(self):
        first = generate_demo(self.root / "first.glb")
        second = generate_demo(self.root / "second.glb")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        report = inspect_glb(first)
        self.assertEqual(report["counts"]["materials"], 2)
        self.assertEqual(report["counts"]["meshes"], 2)
        self.assertEqual(report["counts"]["animations"], 1)
        self.assertEqual([p["triangles_declared"] for p in report["primitives"]], [1, 2])
        self.assertEqual(report["limitations"], [])
        self.assertTrue(compare_glbs(first, second)["preserved"])

    def test_refuses_overwriting_existing_file(self):
        path = self.root / "existing.glb"
        path.write_bytes(b"keep me")
        with self.assertRaises(FileExistsError):
            generate_demo(path)
        self.assertEqual(path.read_bytes(), b"keep me")

    def test_missing_parent_is_not_created(self):
        with self.assertRaises(FileNotFoundError):
            generate_demo(self.root / "missing" / "demo.glb")


if __name__ == "__main__":
    unittest.main()
