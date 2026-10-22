"""Verify local evidence without extracting archives or executing their contents.

Supported manifests: this repository's checkpoint .manifest.json format, and
path -> {sha256, bytes} file maps. Digests establish identity, not authenticity.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_PAYLOAD_BYTES = 4 * 1024**3
MAX_MEMBERS = 20000


class ManifestError(ValueError):
    """The manifest or archive cannot be safely interpreted."""


def _relative(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ManifestError("Expected a portable relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise ManifestError(f"Unsafe relative path: {value!r}")
    if any(ord(c) < 32 for c in value):
        raise ManifestError("Control character in path")
    for part in path.parts:
        if part.endswith((".", " ")) or any(c in part for c in '<>"|?*'):
            raise ManifestError("Non-portable Windows path component")
        stem = part.split(".", 1)[0].upper()
        if stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", stem):
            raise ManifestError("Reserved Windows device path")
    return value


def _local(root, name):
    name = _relative(name)
    root = Path(root).resolve(strict=True)
    target = root.joinpath(*PurePosixPath(name).parts)
    current = root
    for part in PurePosixPath(name).parts:
        current = current / part
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise ManifestError(f"Symlink not permitted: {name}")
    if not target.resolve().is_relative_to(root):
        raise ManifestError(f"Path escapes root: {name}")
    return target


def _hash(stream, limit):
    digest = hashlib.sha256()
    total = 0
    while chunk := stream.read(1024 * 1024):
        total += len(chunk)
        if total > limit:
            raise ManifestError("Payload exceeds configured byte limit")
        digest.update(chunk)
    return total, digest.hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(data) > MAX_MANIFEST_BYTES:
        raise ManifestError("Manifest exceeds size limit")
    return json.loads(data, object_pairs_hook=_unique_object)


def _records(rows):
    if not isinstance(rows, list) or not rows or len(rows) > MAX_MEMBERS:
        raise ManifestError("Manifest requires a nonempty bounded list of files")
    entries = {}
    folded = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ManifestError("Invalid file record")
        name = _relative(row.get("path"))
        if name.casefold() in folded:
            raise ManifestError(f"Duplicate or case-colliding path: {name}")
        size, digest = row.get("bytes"), row.get("sha256")
        if type(size) is not int or size < 0 or size > MAX_PAYLOAD_BYTES:
            raise ManifestError(f"Invalid size: {name}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ManifestError(f"Invalid SHA-256: {name}")
        entries[name] = {"bytes": size, "sha256": digest}
        folded.add(name.casefold())
    if sum(r["bytes"] for r in entries.values()) > MAX_PAYLOAD_BYTES:
        raise ManifestError("Total declared payload exceeds size limit")
    return entries


def verify_files(manifest, root=None):
    """Check a file-map manifest against explicit root (default: manifest parent).

    Only declared files are checked. Extra files are not a failure.
    """
    manifest = Path(manifest)
    data = _read_json(manifest)
    if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
        raise ManifestError("Expected path -> {bytes, sha256} manifest")
    entries = _records([dict(v, path=k) for k, v in data.items()])
    root = Path(root) if root is not None else manifest.parent
    failures = []
    matched = 0
    for name, entry in entries.items():
        path = _local(root, name)
        if not path.is_file():
            failures.append({"path": name, "reason": "missing_or_not_file"})
            continue
        if path.stat().st_size != entry["bytes"]:
            failures.append({"path": name, "reason": "size_mismatch"})
            continue
        with path.open("rb") as stream:
            size, digest = _hash(stream, entry["bytes"])
        if size != entry["bytes"] or digest != entry["sha256"]:
            failures.append({"path": name, "reason": "hash_mismatch"})
        else:
            matched += 1
    return {"schema_version": 1, "operation": "verify_files", "ok": not failures,
            "declared_files": len(entries), "matched_files": matched, "failures": failures,
            "scope": "Declared file bytes only; extra files, scientific validity and rights are not checked."}


def verify_checkpoint(manifest):
    """Verify archive hash, exact member set, embedded manifest and every member.

    The ZIP is read in bounded chunks; it is never extracted or executed.
    """
    manifest = Path(manifest)
    data = _read_json(manifest)
    if not isinstance(data, dict):
        raise ManifestError("Expected checkpoint manifest object")
    entries = _records(data.get("payload_files"))
    if any(name.casefold() == "checkpoint_contents.json" for name in entries):
        raise ManifestError("Reserved checkpoint metadata path")
    archive_record = _records([{"path": data.get("archive"), "bytes": data.get("archive_bytes"),
                                "sha256": data.get("archive_sha256")}])
    name, record = next(iter(archive_record.items()))
    archive = _local(manifest.parent, name)
    if record["bytes"] > MAX_ARCHIVE_BYTES:
        raise ManifestError("Archive exceeds size limit")
    result = {"schema_version": 1, "operation": "verify_checkpoint", "archive": name,
              "ok": False, "declared_files": len(entries), "matched_files": 0, "failures": [],
              "scope": "Local manifest and archive byte identity only; no extraction, execution, authenticity or scientific validation."}
    if not archive.is_file() or archive.stat().st_size != record["bytes"]:
        result["failures"].append({"path": name, "reason": "missing_or_size_mismatch"})
        return result
    with archive.open("rb") as stream:
        size, digest = _hash(stream, MAX_ARCHIVE_BYTES)
    if size != record["bytes"] or digest != record["sha256"]:
        result["failures"].append({"path": name, "reason": "archive_hash_mismatch"})
        return result
    with zipfile.ZipFile(archive) as zipped:
        infos = zipped.infolist()
        names = [i.filename for i in infos]
        if len(infos) > MAX_MEMBERS + 1 or len(set(names)) != len(names):
            raise ManifestError("Too many or duplicate ZIP members")
        if set(names) != set(entries) | {"CHECKPOINT_CONTENTS.json"}:
            raise ManifestError("Archive member set differs from manifest")
        for info in infos:
            _relative(info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                raise ManifestError("Archive contains non-regular file")
            if info.flag_bits & 1:
                raise ManifestError("Encrypted ZIP members are unsupported")
            limit = MAX_MANIFEST_BYTES if info.filename == "CHECKPOINT_CONTENTS.json" else entries[info.filename]["bytes"]
            if info.file_size > limit:
                raise ManifestError("Archive member exceeds declared size")
        metadata = json.loads(zipped.read("CHECKPOINT_CONTENTS.json"), object_pairs_hook=_unique_object)
        if metadata != data["payload_files"]:
            raise ManifestError("Embedded checkpoint manifest differs")
        for name, entry in entries.items():
            with zipped.open(name) as stream:
                size, digest = _hash(stream, entry["bytes"])
            if size != entry["bytes"] or digest != entry["sha256"]:
                result["failures"].append({"path": name, "reason": "payload_mismatch"})
            else:
                result["matched_files"] += 1
    result["ok"] = not result["failures"]
    return result
