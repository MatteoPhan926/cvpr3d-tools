"""Bounded, read-only GLB 2 container inspection; not a glTF validator or renderer.

Only standard-library modules are used. No URI is fetched or opened. Geometry,
animation samples, and image pixels are never decoded. Counts are declarations,
not measurements of a rendered scene. This generalizes the historical inspector
in ``trellis2_route_resolution_20261009/source/inspect_glb.py``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from pathlib import Path
import struct
from typing import Any


MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024
_JSON = 0x4E4F534A
_BIN = 0x004E4942
_COMPONENT_BYTES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
_ELEMENT_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
                       "MAT2": 4, "MAT3": 9, "MAT4": 16}
_ARRAYS = ("buffers", "bufferViews", "accessors", "images", "textures", "samplers",
           "materials", "meshes", "nodes", "scenes", "animations", "skins", "cameras")
_SCOPE = (
    "Container structure and declared references only; this is not full glTF schema validation.",
    "Geometry, image pixels, and animation samples are not decoded or validated; counts come from accessor declarations.",
    "No assessment of appearance, topology, rigging quality, provenance, licensing, or production readiness.",
)


class GLBError(ValueError):
    """Malformed or out-of-bounds GLB input, or an exceeded inspection limit."""


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise GLBError(f"{label} must be an integer >= {minimum}")
    return value


def _object(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise GLBError(f"{label} must be an object")
    return value


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise GLBError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise GLBError(f"Non-finite JSON number: {value}")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise GLBError(f"JSON number is outside the finite float range: {value}")
    return result


def _read(path: str | Path) -> tuple[bytes, dict, memoryview | None, list[dict]]:
    source = Path(path)
    with source.open("rb") as handle:
        header = handle.read(12)
        if len(header) != 12:
            raise GLBError("Truncated GLB header")
        magic, version, total = struct.unpack("<4sII", header)
        if magic != b"glTF" or version != 2:
            raise GLBError("Expected a GLB version 2 header")
        if total < 20 or total > MAX_FILE_BYTES:
            raise GLBError(f"Declared GLB size must be between 20 and {MAX_FILE_BYTES} bytes")
        data = header + handle.read(total - 12)
        if len(data) != total or handle.read(1):
            raise GLBError("GLB length does not match the header")
    offset = 12
    document = None
    binary = None
    chunks = []
    while offset < total:
        if total - offset < 8:
            raise GLBError("Truncated chunk header")
        size, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        if size % 4 or size > total - offset:
            raise GLBError("Chunk is unaligned or extends beyond the file")
        if not chunks and kind != _JSON:
            raise GLBError("The first GLB chunk must be JSON")
        chunk = memoryview(data)[offset:offset + size]
        if kind == _JSON:
            if document is not None:
                raise GLBError("Multiple JSON chunks are not permitted")
            if size > MAX_JSON_BYTES:
                raise GLBError(f"JSON exceeds the {MAX_JSON_BYTES}-byte inspection limit")
            try:
                document = json.loads(bytes(chunk).decode("utf-8"),
                                      object_pairs_hook=_unique_object,
                                      parse_float=_finite_float,
                                      parse_constant=_reject_constant)
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
                raise GLBError(f"Invalid GLB JSON: {exc}") from exc
            _object(document, "document")
        elif kind == _BIN:
            if binary is not None or len(chunks) != 1:
                raise GLBError("At most one BIN chunk is allowed, immediately after JSON")
            binary = chunk
        chunks.append({"type": f"0x{kind:08x}", "bytes": size})
        offset += size
    if document is None:
        raise GLBError("Missing JSON chunk")
    return data, document, binary, chunks


def _validate(document: dict, binary: memoryview | None) -> tuple[dict, list[str]]:
    asset = _object(document.get("asset"), "asset")
    if asset.get("version") != "2.0":
        raise GLBError("asset.version must be 2.0")
    arrays = {}
    limitations = []
    for name in _ARRAYS:
        entries = document.get(name, [])
        if not isinstance(entries, list):
            raise GLBError(f"{name} must be an array")
        for index, entry in enumerate(entries):
            _object(entry, f"{name}[{index}]")
        arrays[name] = entries

    def ref(name: str, value: Any, label: str) -> dict:
        index = _integer(value, label)
        if index >= len(arrays[name]):
            raise GLBError(f"{label} references missing {name}[{index}]")
        return arrays[name][index]

    def refs(name: str, values: Any, label: str) -> None:
        if not isinstance(values, list):
            raise GLBError(f"{label} must be an array")
        for value in values:
            ref(name, value, label)

    for name in ("extensionsUsed", "extensionsRequired"):
        values = document.get(name, [])
        if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
            raise GLBError(f"{name} must be an array of strings")
    if not set(document.get("extensionsRequired", [])).issubset(document.get("extensionsUsed", [])):
        raise GLBError("extensionsRequired must be included in extensionsUsed")
    if asset.get("minVersion", "2.0") != "2.0":
        limitations.append("asset.minVersion is not 2.0; newer semantics are unsupported.")
    for index, buffer in enumerate(arrays["buffers"]):
        length = _integer(buffer.get("byteLength"), f"buffers[{index}].byteLength", 1)
        if "uri" in buffer:
            if not isinstance(buffer["uri"], str):
                raise GLBError("buffer.uri must be a string")
            limitations.append(f"buffers[{index}] uses a URI; its content is not loaded or checked.")
        else:
            if index != 0 or binary is None:
                raise GLBError("Only buffer 0 may use the GLB BIN chunk, which must exist")
            if not length <= len(binary) <= length + 3:
                raise GLBError("BIN chunk length does not match buffer 0 (including up to 3 padding bytes)")
    if binary is not None and (not arrays["buffers"] or "uri" in arrays["buffers"][0]):
        raise GLBError("BIN chunk has no corresponding embedded buffer 0")
    for index, view in enumerate(arrays["bufferViews"]):
        buffer = ref("buffers", view.get("buffer"), f"bufferViews[{index}].buffer")
        start = _integer(view.get("byteOffset", 0), "bufferView.byteOffset")
        length = _integer(view.get("byteLength"), "bufferView.byteLength", 1)
        if start + length > buffer["byteLength"]:
            raise GLBError("bufferView extends beyond its declared buffer")
        if "byteStride" in view:
            stride = _integer(view["byteStride"], "bufferView.byteStride", 4)
            if stride > 252 or stride % 4:
                raise GLBError("bufferView.byteStride must be a multiple of 4 in [4, 252]")

    for index, accessor in enumerate(arrays["accessors"]):
        label = f"accessors[{index}]"
        count = _integer(accessor.get("count"), f"{label}.count", 1)
        component = accessor.get("componentType")
        kind = accessor.get("type")
        if type(component) is not int or component not in _COMPONENT_BYTES:
            raise GLBError(f"{label} has an invalid componentType")
        if not isinstance(kind, str) or kind not in _ELEMENT_COMPONENTS:
            raise GLBError(f"{label} has an invalid type")
        width = _COMPONENT_BYTES[component]
        element = width * _ELEMENT_COMPONENTS[kind]
        if kind.startswith("MAT"):
            rows = int(kind[-1])
            element = ((width * rows + 3) // 4 * 4) * rows
        start = _integer(accessor.get("byteOffset", 0), f"{label}.byteOffset")
        if start % width:
            raise GLBError(f"{label}.byteOffset is not component aligned")
        if "bufferView" in accessor:
            view = ref("bufferViews", accessor["bufferView"], f"{label}.bufferView")
            stride = view.get("byteStride", element)
            if stride < element or stride % width:
                raise GLBError(f"{label} has an invalid element stride")
            if start + (count - 1) * stride + element > view["byteLength"]:
                raise GLBError(f"{label} extends beyond its bufferView")
        elif start:
            raise GLBError(f"{label} has byteOffset without bufferView")
        if "sparse" in accessor:
            sparse = _object(accessor["sparse"], f"{label}.sparse")
            sparse_count = _integer(sparse.get("count"), "sparse.count", 1)
            if sparse_count > count:
                raise GLBError("sparse.count exceeds accessor.count")
            for part in ("indices", "values"):
                entry = _object(sparse.get(part), f"sparse.{part}")
                view = ref("bufferViews", entry.get("bufferView"), f"sparse.{part}.bufferView")
                part_width = element
                if part == "indices":
                    ct = entry.get("componentType")
                    if type(ct) is not int or ct not in (5121, 5123, 5125):
                        raise GLBError("Invalid sparse index componentType")
                    part_width = _COMPONENT_BYTES[ct]
                start = _integer(entry.get("byteOffset", 0), f"sparse.{part}.byteOffset")
                if start + sparse_count * part_width > view["byteLength"]:
                    raise GLBError(f"sparse.{part} extends beyond its bufferView")
    for index, image in enumerate(arrays["images"]):
        if ("uri" in image) == ("bufferView" in image):
            raise GLBError(f"images[{index}] must specify exactly one of uri and bufferView")
        if "bufferView" in image:
            ref("bufferViews", image["bufferView"], f"images[{index}].bufferView")
            if not isinstance(image.get("mimeType"), str):
                raise GLBError("An image stored in a bufferView requires mimeType")
        elif not isinstance(image["uri"], str):
            raise GLBError("image.uri must be a string")
    for index, texture in enumerate(arrays["textures"]):
        for name, array in (("source", "images"), ("sampler", "samplers")):
            if name in texture:
                ref(array, texture[name], f"textures[{index}].{name}")
        for extension, entry in _object(texture.get("extensions", {}), "texture.extensions").items():
            if extension in ("KHR_texture_basisu", "EXT_texture_webp", "EXT_texture_avif"):
                ref("images", _object(entry, extension).get("source"), f"{extension}.source")
    for material in arrays["materials"]:
        slots = [(material, name) for name in ("normalTexture", "occlusionTexture", "emissiveTexture")]
        pbr = _object(material.get("pbrMetallicRoughness", {}), "pbrMetallicRoughness")
        slots.extend((pbr, name) for name in ("baseColorTexture", "metallicRoughnessTexture"))
        for owner, name in slots:
            if name in owner:
                info = _object(owner[name], name)
                ref("textures", info.get("index"), f"{name}.index")
    for mi, mesh in enumerate(arrays["meshes"]):
        primitives = mesh.get("primitives")
        if not isinstance(primitives, list) or not primitives:
            raise GLBError(f"meshes[{mi}].primitives must be a nonempty array")
        for primitive in primitives:
            _object(primitive, "primitive")
            attributes = _object(primitive.get("attributes"), "primitive.attributes")
            for value in attributes.values():
                ref("accessors", value, "primitive attribute")
            for name, array in (("indices", "accessors"), ("material", "materials")):
                if name in primitive:
                    ref(array, primitive[name], f"primitive.{name}")
            mode = _integer(primitive.get("mode", 4), "primitive.mode")
            if mode > 6:
                raise GLBError("primitive.mode must be in [0, 6]")
            targets = primitive.get("targets", [])
            if not isinstance(targets, list):
                raise GLBError("primitive.targets must be an array")
            for target in targets:
                for value in _object(target, "morph target").values():
                    ref("accessors", value, "morph target accessor")
            extensions = _object(primitive.get("extensions", {}), "primitive.extensions")
            if "KHR_draco_mesh_compression" in extensions:
                draco = _object(extensions["KHR_draco_mesh_compression"], "Draco extension")
                ref("bufferViews", draco.get("bufferView"), "Draco bufferView")
    for node in arrays["nodes"]:
        for name, array in (("mesh", "meshes"), ("skin", "skins"), ("camera", "cameras")):
            if name in node:
                ref(array, node[name], f"node.{name}")
        refs("nodes", node.get("children", []), "node.children")
    for scene in arrays["scenes"]:
        refs("nodes", scene.get("nodes", []), "scene.nodes")
    if "scene" in document:
        ref("scenes", document["scene"], "scene")
    for skin in arrays["skins"]:
        refs("nodes", skin.get("joints", []), "skin.joints")
        for name, array in (("skeleton", "nodes"), ("inverseBindMatrices", "accessors")):
            if name in skin:
                ref(array, skin[name], f"skin.{name}")
    for animation in arrays["animations"]:
        samplers = animation.get("samplers")
        channels = animation.get("channels")
        if not isinstance(samplers, list) or not isinstance(channels, list):
            raise GLBError("animation samplers and channels must be arrays")
        for sampler in samplers:
            _object(sampler, "animation sampler")
            for name in ("input", "output"):
                ref("accessors", sampler.get(name), f"animation sampler.{name}")
        for channel in channels:
            _object(channel, "animation channel")
            index = _integer(channel.get("sampler"), "animation channel.sampler")
            if index >= len(samplers):
                raise GLBError("animation channel references missing sampler")
            target = _object(channel.get("target"), "animation target")
            if "node" in target:
                ref("nodes", target["node"], "animation target.node")
    return arrays, limitations


def _images(arrays: dict, binary: memoryview | None) -> list[dict]:
    result = []
    for index, item in enumerate(arrays["images"]):
        row = {"index": index, "mime_type": item.get("mimeType"), "storage": "external_uri",
               "bytes": None, "sha256": None}
        payload = None
        if "bufferView" in item:
            view = arrays["bufferViews"][item["bufferView"]]
            buffer = arrays["buffers"][view["buffer"]]
            row["storage"] = "external_buffer"
            if "uri" not in buffer and binary is not None:
                start = view.get("byteOffset", 0)
                payload = binary[start:start + view["byteLength"]]
                row["storage"] = "bin_buffer_view"
        elif item["uri"].startswith("data:"):
            uri = item["uri"]
            metadata, separator, encoded = uri.partition(",")
            if not separator or not metadata.endswith(";base64"):
                row["storage"] = "unsupported_data_uri"
            else:
                try:
                    payload = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise GLBError(f"images[{index}] has invalid base64 data") from exc
                row["storage"] = "data_uri"
                row["mime_type"] = row["mime_type"] or metadata[5:-7]
        if payload is not None:
            row["bytes"] = len(payload)
            row["sha256"] = hashlib.sha256(payload).hexdigest()
        result.append(row)
    return result


def inspect_glb(path: str | Path) -> dict:
    """Return a JSON-serializable structural report, raising GLBError on malformed input.

    Limits: 512 MiB per file, 16 MiB JSON. External resources are never opened.
    Extension semantics and actual payload validity are outside this API's scope.
    """
    data, document, binary, chunks = _read(path)
    arrays, limitations = _validate(document, binary)
    images = _images(arrays, binary)
    primitives = []
    for mi, mesh in enumerate(arrays["meshes"]):
        for pi, primitive in enumerate(mesh["primitives"]):
            attrs = primitive["attributes"]
            position = attrs.get("POSITION")
            vertices = arrays["accessors"][position]["count"] if position is not None else None
            count = arrays["accessors"][primitive["indices"]]["count"] if "indices" in primitive else vertices
            mode = primitive.get("mode", 4)
            triangles = None
            if count is not None:
                if mode == 4:
                    triangles = count // 3
                elif mode in (5, 6):
                    triangles = max(count - 2, 0)
            primitives.append({"mesh": mi, "primitive": pi, "vertices_declared": vertices,
                               "elements_declared": count, "triangles_declared": triangles,
                               "mode": mode, "material": primitive.get("material"),
                               "attribute_accessors": attrs, "has_uv0": "TEXCOORD_0" in attrs,
                               "has_normals": "NORMAL" in attrs})
    used = document.get("extensionsUsed", [])
    compressed = [name for name in used if name in ("KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_meshopt_compression")]
    if used:
        limitations.append("Extension semantics are not validated: " + ", ".join(used) + ".")
    if compressed:
        limitations.append("Compressed geometry is not decoded; accessor counts remain declarations only.")
    if any(row["sha256"] is None for row in images):
        limitations.append("Some image payloads are unavailable or unsupported; their equality cannot be established.")
    if any(chunk["type"] not in (f"0x{_JSON:08x}", f"0x{_BIN:08x}") for chunk in chunks):
        limitations.append("Unknown GLB chunks were bounded and skipped; their semantics are unsupported.")
    return {"schema_version": 1, "input": Path(path).name, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "container_version": 2,
            "asset_metadata": document["asset"], "chunks": chunks,
            "counts": {**{name: len(entries) for name, entries in arrays.items()}, "primitives": len(primitives)},
            "extensions_used": used, "extensions_required": document.get("extensionsRequired", []),
            "primitives": primitives, "materials": arrays["materials"], "textures": arrays["textures"],
            "samplers": arrays["samplers"], "images": images,
            "geometry": {"decoded": False, "compression_extensions": compressed,
                         "counts_source": "accessor declarations, summed per mesh primitive, not scene instances"},
            "scope": list(_SCOPE), "limitations": limitations}


def compare_glbs(before: str | Path, after: str | Path) -> dict:
    """Compare exact JSON definitions and image payload bytes, not rendered appearance.

    Array order, names, extras, and omitted defaults matter in definition equality.
    Image payloads are compared by image index, MIME type, and SHA-256. Container,
    geometry, UVs, assignments, animation, and extension semantics are not compared.
    An unresolved image yields ``unsupported`` unless another check proves a change.
    """
    left, right = inspect_glb(before), inspect_glb(after)
    # Canonical JSON retains the distinction between booleans and numbers that
    # Python's dict equality would otherwise erase (True == 1).
    checks = {f"{name}_equal": json.dumps(left[name], sort_keys=True) == json.dumps(right[name], sort_keys=True)
              for name in ("materials", "textures", "samplers")}
    unavailable = any(image["sha256"] is None for report in (left, right) for image in report["images"])
    if len(left["images"]) != len(right["images"]):
        payloads_equal = False
    else:
        known_change = any(
            a["mime_type"] != b["mime_type"] or
            (a["sha256"] is not None and b["sha256"] is not None and a["sha256"] != b["sha256"])
            for a, b in zip(left["images"], right["images"]))
        payloads_equal = False if known_change else None if unavailable else True
    checks["image_payloads_equal"] = payloads_equal
    preserved = False if False in checks.values() else None if None in checks.values() else True
    return {"schema_version": 1, "before": {"input": left["input"], "sha256": left["sha256"], "counts": left["counts"]},
            "after": {"input": right["input"], "sha256": right["sha256"], "counts": right["counts"]},
            "status": "equal" if preserved is True else "different" if preserved is False else "unsupported",
            "preserved": preserved, "checks": checks,
            "scope": "Exact material, texture, sampler JSON definitions and image-index/MIME/payload SHA-256 equality only.",
            "limitations": list(dict.fromkeys([
                "Equality does not establish visual equivalence: geometry, UVs, material assignments, animations, and extension semantics are not compared.",
                "Image pixels are not decoded; differently encoded but visually identical images compare as different.",
                *left["limitations"], *right["limitations"]]))}
