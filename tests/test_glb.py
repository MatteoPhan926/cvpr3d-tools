"""Adversarial container tests and material/image comparison contract tests."""

import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest

from cvpr3d.glb import GLBError, compare_glbs, inspect_glb


def pack_glb(document, binary=None, extra_chunks=()):
    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    chunks = struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
    if binary is not None:
        binary += b"\0" * (-len(binary) % 4)
        chunks += struct.pack("<II", len(binary), 0x004E4942) + binary
    for kind, payload in extra_chunks:
        chunks += struct.pack("<II", len(payload), kind) + payload
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


class GLBTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(self, document=None, binary=None, name="input.glb", data=None):
        path = self.root / name
        path.write_bytes(data if data is not None else pack_glb(document, binary))
        return path

    def image_document(self):
        return {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 4}],
                "bufferViews": [{"buffer": 0, "byteLength": 4}],
                "images": [{"bufferView": 0, "mimeType": "image/png"}],
                "samplers": [{"wrapS": 33071}], "textures": [{"source": 0, "sampler": 0}],
                "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]}

    def test_minimal_container_is_not_claimed_to_be_renderable(self):
        report = inspect_glb(self.write({"asset": {"version": "2.0"}}))
        self.assertEqual(report["counts"]["meshes"], 0)
        self.assertEqual(report["input"], "input.glb")
        self.assertFalse(report["geometry"]["decoded"])
        self.assertIn("not full glTF", report["scope"][0])

    def test_embedded_image_hash_and_exact_definition_comparison(self):
        document = self.image_document()
        before = self.write(document, b"abcd", "before.glb")
        after = self.write(document, b"abcd", "after.glb")
        report = inspect_glb(before)
        self.assertEqual(report["images"][0]["bytes"], 4)
        self.assertEqual(report["images"][0]["storage"], "bin_buffer_view")
        self.assertEqual(compare_glbs(before, after)["status"], "equal")
        self.write(document, b"abce", "after.glb")
        comparison = compare_glbs(before, after)
        self.assertFalse(comparison["checks"]["image_payloads_equal"])
        self.assertFalse(comparison["preserved"])

    def test_material_texture_and_sampler_changes_are_detected(self):
        original = self.image_document()
        before = self.write(original, b"abcd", "before.glb")
        for field in ("materials", "textures", "samplers"):
            changed = copy.deepcopy(original)
            changed[field][0]["name"] = "new name"
            after = self.write(changed, b"abcd", "after.glb")
            with self.subTest(field=field):
                comparison = compare_glbs(before, after)
                self.assertFalse(comparison["checks"][field + "_equal"])
                self.assertEqual(comparison["status"], "different")

    def test_external_image_is_not_loaded_or_reported_equal(self):
        for uri in ("../../secret.png", "https://example.invalid/picture.png"):
            with self.subTest(uri=uri):
                path = self.write({"asset": {"version": "2.0"}, "images": [{"uri": uri}]})
                report = compare_glbs(path, path)
                self.assertEqual(report["status"], "unsupported")
                self.assertIsNone(report["preserved"])
                self.assertIsNone(report["checks"]["image_payloads_equal"])

    def test_external_buffer_image_is_unsupported(self):
        document = self.image_document()
        document["buffers"][0]["uri"] = "not-loaded.bin"
        path = self.write(document)
        self.assertEqual(inspect_glb(path)["images"][0]["storage"], "external_buffer")
        self.assertIsNone(compare_glbs(path, path)["preserved"])

    def test_data_uri_supported_without_image_decoding(self):
        path = self.write({"asset": {"version": "2.0"}, "images": [{"uri": "data:image/png;base64,YWJjZA=="}]})
        image = inspect_glb(path)["images"][0]
        self.assertEqual(image["bytes"], 4)
        self.assertEqual(image["mime_type"], "image/png")
        self.assertEqual(compare_glbs(path, path)["status"], "equal")

    def test_unsupported_or_invalid_data_uri(self):
        path = self.write({"asset": {"version": "2.0"}, "images": [{"uri": "data:image/png,abcd"}]})
        self.assertEqual(compare_glbs(path, path)["status"], "unsupported")
        path = self.write({"asset": {"version": "2.0"}, "images": [{"uri": "data:image/png;base64,!!"}]})
        with self.assertRaises(GLBError):
            inspect_glb(path)

    def test_compressed_geometry_counts_are_only_declarations(self):
        document = {"asset": {"version": "2.0"}, "extensionsUsed": ["KHR_draco_mesh_compression"],
                    "extensionsRequired": ["KHR_draco_mesh_compression"], "buffers": [{"byteLength": 4}],
                    "bufferViews": [{"buffer": 0, "byteLength": 4}],
                    "accessors": [{"componentType": 5126, "type": "VEC3", "count": 3}],
                    "meshes": [{"primitives": [{"attributes": {"POSITION": 0},
                                "extensions": {"KHR_draco_mesh_compression": {"bufferView": 0, "attributes": {"POSITION": 0}}}}]}]}
        # Deliberately not a valid Draco stream: no decoding/validation is claimed.
        path = self.write(document, b"fake")
        report = inspect_glb(path)
        self.assertEqual(report["primitives"][0]["triangles_declared"], 1)
        self.assertIn("KHR_draco_mesh_compression", report["geometry"]["compression_extensions"])
        self.assertTrue(any("Compressed geometry is not decoded" in x for x in report["limitations"]))
        self.assertIn("geometry", compare_glbs(path, path)["limitations"][0])

    def test_header_and_chunk_corruption_rejected(self):
        valid = pack_glb({"asset": {"version": "2.0"}})
        bad_magic = b"FAIL" + valid[4:]
        bad_version = valid[:4] + struct.pack("<I", 1) + valid[8:]
        bad_chunk_length = valid[:12] + struct.pack("<I", 0xFFFFFFFC) + valid[16:]
        bad_alignment = valid[:12] + struct.pack("<I", 3) + valid[16:]
        not_json_first = valid[:16] + struct.pack("<I", 0x004E4942) + valid[20:]
        bad_total = valid[:8] + struct.pack("<I", 600 * 1024 * 1024) + valid[12:]
        for data in (b"", valid[:10], valid[:-1], valid + b"x", bad_magic,
                     bad_version, bad_chunk_length, bad_alignment, not_json_first, bad_total):
            with self.subTest(data=data[:20]):
                with self.assertRaises(GLBError):
                    inspect_glb(self.write(data=data))

    def test_truncated_chunk_header(self):
        valid = pack_glb({"asset": {"version": "2.0"}})
        data = valid[:8] + struct.pack("<I", len(valid) + 4) + valid[12:] + b"abcd"
        with self.assertRaisesRegex(GLBError, "chunk header"):
            inspect_glb(self.write(data=data))

    def test_duplicate_chunks_rejected_unknown_chunk_explained(self):
        document = {"asset": {"version": "2.0"}}
        with self.assertRaises(GLBError):
            inspect_glb(self.write(data=pack_glb(document, extra_chunks=[(0x4E4F534A, b"{}  ")])))
        report = inspect_glb(self.write(data=pack_glb(document, extra_chunks=[(12345, b"abcd")])))
        self.assertTrue(any("Unknown GLB chunks" in x for x in report["limitations"]))

    def test_bad_json_types_and_nonfinite_numbers(self):
        for document in ([], {"asset": {}}, {"asset": {"version": "2.0"}, "meshes": {}},
                         {"asset": {"version": "2.0"}, "extras": float("nan")}):
            with self.subTest(document=document):
                with self.assertRaises(GLBError):
                    inspect_glb(self.write(document))

    def test_duplicate_json_keys_rejected(self):
        raw = b'{"asset":{"version":"2.0"},"asset":{"version":"2.0"}}'
        raw += b" " * (-len(raw) % 4)
        data = struct.pack("<4sIIII", b"glTF", 2, 20 + len(raw), len(raw), 0x4E4F534A) + raw
        with self.assertRaisesRegex(GLBError, "Duplicate JSON key"):
            inspect_glb(self.write(data=data))

    def test_float_overflow_rejected(self):
        raw = b'{"asset":{"version":"2.0"},"extras":1e999}'
        raw += b" " * (-len(raw) % 4)
        data = struct.pack("<4sIIII", b"glTF", 2, 20 + len(raw), len(raw), 0x4E4F534A) + raw
        with self.assertRaisesRegex(GLBError, "finite float range"):
            inspect_glb(self.write(data=data))

    def test_exact_definition_comparison_distinguishes_bool_from_int(self):
        document = self.image_document()
        document["materials"][0]["extras"] = {"example": True}
        before = self.write(document, b"abcd", "before.glb")
        document["materials"][0]["extras"] = {"example": 1}
        after = self.write(document, b"abcd", "after.glb")
        self.assertFalse(compare_glbs(before, after)["checks"]["materials_equal"])

    def test_known_image_change_is_not_hidden_by_an_unavailable_image(self):
        document = self.image_document()
        document["images"].append({"uri": "unavailable.png"})
        before = self.write(document, b"abcd", "before.glb")
        after = self.write(document, b"abce", "after.glb")
        self.assertEqual(compare_glbs(before, after)["status"], "different")

    def test_invalid_reference_domains(self):
        for value in (-1, 1, True, "0", None):
            document = self.image_document()
            document["textures"][0]["source"] = value
            with self.subTest(value=value):
                with self.assertRaises(GLBError):
                    inspect_glb(self.write(document, b"abcd"))

    def test_invalid_material_image_buffer_and_animation_refs(self):
        original = self.image_document()
        mutations = [
            lambda d: d["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"].update(index=2),
            lambda d: d["images"][0].update(bufferView=1),
            lambda d: d["bufferViews"][0].update(buffer=1),
            lambda d: d.update(nodes=[{"mesh": 0}]),
            lambda d: d.update(scenes=[{"nodes": [0]}]),
            lambda d: d.update(animations=[{"samplers": [], "channels": [{"sampler": 0, "target": {"node": 0}}]}]),
        ]
        for mutation in mutations:
            document = copy.deepcopy(original)
            mutation(document)
            with self.subTest(document=document):
                with self.assertRaises(GLBError):
                    inspect_glb(self.write(document, b"abcd"))

    def test_buffer_view_and_accessor_bounds(self):
        document = self.image_document()
        document["bufferViews"][0]["byteLength"] = 5
        with self.assertRaises(GLBError):
            inspect_glb(self.write(document, b"abcd"))
        document = self.image_document()
        document["accessors"] = [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}]
        with self.assertRaisesRegex(GLBError, "extends beyond"):
            inspect_glb(self.write(document, b"abcd"))

    def test_bin_without_buffer_and_missing_bin(self):
        with self.assertRaises(GLBError):
            inspect_glb(self.write({"asset": {"version": "2.0"}}, b"abcd"))
        with self.assertRaises(GLBError):
            inspect_glb(self.write(self.image_document()))

    def test_sparse_bounds_rejected(self):
        document = self.image_document()
        document["accessors"] = [{"componentType": 5126, "count": 2, "type": "VEC3", "sparse": {
            "count": 2, "indices": {"bufferView": 0, "componentType": 5121}, "values": {"bufferView": 0}}}]
        with self.assertRaisesRegex(GLBError, "sparse.values extends beyond"):
            inspect_glb(self.write(document, b"abcd"))

    def test_image_count_change_proves_difference_even_if_external(self):
        before = self.write({"asset": {"version": "2.0"}}, name="before.glb")
        after = self.write({"asset": {"version": "2.0"}, "images": [{"uri": "external.png"}]}, name="after.glb")
        self.assertEqual(compare_glbs(before, after)["status"], "different")


if __name__ == "__main__":
    unittest.main()
