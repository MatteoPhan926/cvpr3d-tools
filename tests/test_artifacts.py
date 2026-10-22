import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from cvpr3d.artifacts import ManifestError, verify_checkpoint, verify_files


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def checkpoint(self, payload=b"evidence", member="evidence.txt", expected=None, extras=None):
        expected = payload if expected is None else expected
        records = [{"path": member, "bytes": len(expected), "sha256": hashlib.sha256(expected).hexdigest()}]
        archive = self.root / "checkpoint.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr(member, payload)
            zipped.writestr("CHECKPOINT_CONTENTS.json", json.dumps(records))
            for name, content in (extras or {}).items():
                zipped.writestr(name, content)
        data = archive.read_bytes()
        manifest = self.root / "checkpoint.manifest.json"
        manifest.write_text(json.dumps({"archive": archive.name, "archive_bytes": len(data),
                                       "archive_sha256": hashlib.sha256(data).hexdigest(),
                                       "payload_files": records}), encoding="utf-8")
        return manifest

    def test_verifies_every_member_without_extracting(self):
        result = verify_checkpoint(self.checkpoint())
        self.assertTrue(result["ok"])
        self.assertEqual(result["matched_files"], 1)
        self.assertFalse((self.root / "evidence.txt").exists())

    def test_tampered_archive_fails_before_reading_members(self):
        manifest = self.checkpoint()
        archive = self.root / "checkpoint.zip"
        data = bytearray(archive.read_bytes())
        data[32] ^= 1
        archive.write_bytes(data)
        result = verify_checkpoint(manifest)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"][0]["reason"], "archive_hash_mismatch")

    def test_outer_hash_does_not_hide_payload_mismatch(self):
        result = verify_checkpoint(self.checkpoint(payload=b"changed!", expected=b"original"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["matched_files"], 0)

    def test_rejects_extra_member(self):
        with self.assertRaises(ManifestError):
            verify_checkpoint(self.checkpoint(extras={"unlisted.txt": b"surprise"}))

    def test_rejects_case_collision_with_reserved_metadata(self):
        with self.assertRaises(ManifestError):
            verify_checkpoint(self.checkpoint(member="checkpoint_contents.json"))

    def test_rejects_unsafe_member_names_on_all_platforms(self):
        for member in ("../outside", "/absolute", "C:/drive", "folder\\file", "a/../b", "a//b",
                       "evidence.", "evidence ", "CON", "aux.txt", "COM1", "a/PRN.json", "a?b"):
            with self.subTest(member=member), self.assertRaises(ManifestError):
                verify_checkpoint(self.checkpoint(member=member))

    def test_rejects_duplicate_json_keys(self):
        path = self.root / "manifest.json"
        path.write_text('{"file": {}, "file": {}}', encoding="utf-8")
        with self.assertRaises(ManifestError):
            verify_files(path)

    def test_verify_file_map_reports_missing_changed_and_matching(self):
        payload = b"original"
        entry = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({n: entry for n in ("same", "changed", "missing")}), encoding="utf-8")
        (self.root / "same").write_bytes(payload)
        (self.root / "changed").write_bytes(b"modified")
        result = verify_files(manifest)
        self.assertFalse(result["ok"])
        self.assertEqual(result["matched_files"], 1)
        self.assertEqual({e["reason"] for e in result["failures"]}, {"hash_mismatch", "missing_or_not_file"})

    def test_rejects_invalid_record_types_and_empty_manifest(self):
        manifest = self.root / "bad.json"
        for document in ({}, {"a": {"bytes": True, "sha256": "a" * 64}},
                         {"a": {"bytes": 1, "sha256": "bad"}}):
            manifest.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ManifestError):
                verify_files(manifest)

    def test_rejects_case_collisions(self):
        manifest = self.root / "bad.json"
        entry = {"bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()}
        manifest.write_text(json.dumps({"File": entry, "file": entry}), encoding="utf-8")
        with self.assertRaises(ManifestError):
            verify_files(manifest)

    def test_rejects_symlink(self):
        target = self.root / "real"
        target.write_bytes(b"x")
        link = self.root / "link"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Symlink creation unavailable on this host")
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({"link": {"bytes": 1, "sha256": hashlib.sha256(b"x").hexdigest()}}))
        with self.assertRaises(ManifestError):
            verify_files(manifest)
