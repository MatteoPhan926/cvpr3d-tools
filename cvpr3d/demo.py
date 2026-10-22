"""An original deterministic synthetic GLB fixture, with no downloaded assets."""

from __future__ import annotations

import json
from pathlib import Path
import struct


def generate_demo(output_path: str | Path) -> Path:
    """Create an animated hinged panel and static triangle, refusing to overwrite.

    This is a tiny interoperability fixture, not a reconstruction result or a
    demonstration of automatic semantic part discovery or production rigging.
    The output's parent directory must already exist.
    """
    binary = bytearray()
    views = []
    accessors = []

    def add(values: tuple, fmt: str, component: int, kind: str, count: int,
            bounds: tuple | None = None, target: int | None = None) -> int:
        binary.extend(b"\0" * (-len(binary) % 4))
        payload = struct.pack("<" + fmt, *values)
        view = {"buffer": 0, "byteOffset": len(binary), "byteLength": len(payload)}
        if target is not None:
            view["target"] = target
        views.append(view)
        binary.extend(payload)
        accessor = {"bufferView": len(views) - 1, "componentType": component, "count": count, "type": kind}
        if bounds is not None:
            accessor["min"], accessor["max"] = bounds
        accessors.append(accessor)
        return len(accessors) - 1

    triangle = add((-1.5, 0., 0., -.5, 0., 0., -1., 1., 0.), "9f", 5126, "VEC3", 3,
                   ([-1.5, 0, 0], [-.5, 1, 0]), 34962)
    panel = add((0., 0., 0., 1., 0., 0., 1., 1., 0., 0., 1., 0.), "12f", 5126, "VEC3", 4,
                ([0, 0, 0], [1, 1, 0]), 34962)
    indices = add((0, 1, 2, 0, 2, 3), "6H", 5123, "SCALAR", 6, target=34963)
    times = add((0., 1., 2.), "3f", 5126, "SCALAR", 3, ([0], [2]))
    # Unit quaternions around the local Y hinge: closed, 90 degrees, closed.
    rotations = add((0., 0., 0., 1., 0., 0.7071067811865476, 0., 0.7071067811865476,
                     0., 0., 0., 1.), "12f", 5126, "VEC4", 3)
    document = {
        "asset": {"version": "2.0", "generator": "cvpr3d synthetic demo", "copyright": "Copyright 2026 CVPR_3D contributors. MIT licensed synthetic fixture; no third-party assets."},
        "scene": 0,
        "scenes": [{"name": "Synthetic interoperability fixture", "nodes": [0, 1]}],
        "nodes": [{"name": "Static triangle", "mesh": 0}, {"name": "Hinged panel", "mesh": 1}],
        "meshes": [
            {"name": "Triangle", "primitives": [{"attributes": {"POSITION": triangle}, "material": 0}]},
            {"name": "Panel", "primitives": [{"attributes": {"POSITION": panel}, "indices": indices, "material": 1}]},
        ],
        "materials": [
            {"name": "Triangle blue", "doubleSided": True, "pbrMetallicRoughness": {"baseColorFactor": [.1, .3, .8, 1], "metallicFactor": 0, "roughnessFactor": .8}},
            {"name": "Panel orange", "doubleSided": True, "pbrMetallicRoughness": {"baseColorFactor": [.9, .3, .05, 1], "metallicFactor": 0, "roughnessFactor": .8}},
        ],
        "animations": [{"name": "Synthetic hinge motion", "samplers": [{"input": times, "output": rotations, "interpolation": "LINEAR"}],
                        "channels": [{"sampler": 0, "target": {"node": 1, "path": "rotation"}}]}],
        "buffers": [{"byteLength": len(binary)}], "bufferViews": views, "accessors": accessors,
        "extras": {"purpose": "Hand-authored synthetic fixture; no AI reconstruction or automatic part discovery."},
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    binary.extend(b"\0" * (-len(binary) % 4))
    data = (struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(encoded) + 8 + len(binary))
            + struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
            + struct.pack("<II", len(binary), 0x004E4942) + binary)
    path = Path(output_path)
    with path.open("xb") as handle:
        handle.write(data)
    return path
