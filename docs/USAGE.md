# Usage and limits

Every runtime command works offline. `inspect`, `compare`, `verify-files` and
`verify-checkpoint` print JSON or exclusively create a file with `--output`.
The parent directory must already exist. Existing reports are never overwritten.

Exit code 0 means the operation completed; 1 means an integrity mismatch or a
different/unsupported comparison when `--require-preserved` is used; 2 means
invalid arguments, malformed input or I/O failure. Without that flag, comparison
returns 0 even if the report describes differences.

GLB limits: 512 MiB file, 16 MiB JSON. Counts come from accessor declarations;
geometry, image pixels and animation samples are not decoded. External URI
resources are never fetched/opened. Some embedded data-URI images are supported;
unavailable image bytes cannot produce an equality claim. Unknown extensions
and compressed geometry are reported with explicit limitations.

Comparison checks exact material/texture/sampler JSON definitions and image
index/MIME/payload hashes. Array order, names, extras and omitted defaults matter.
An exporter can produce a harmless difference; matching data can accompany
different geometry/UVs/material assignments. Neither result is a visual judgment.

## Verify your own file manifest

In a new scratch directory, create a small fixture and manifest with Python:

```python
import hashlib, json
from pathlib import Path
payload = b"example evidence\n"
with Path("example.txt").open("xb") as stream:
    stream.write(payload)
with Path("manifest.json").open("x", encoding="utf-8") as stream:
    json.dump({"example.txt": {"bytes": len(payload),
              "sha256": hashlib.sha256(payload).hexdigest()}}, stream)
```

Run `python -m cvpr3d verify-files manifest.json`. Files resolve relative to the
manifest directory, or an explicit `--root DIRECTORY`. Only declared files are
checked; extra files are not a failure. Empty manifests are rejected.

## Checkpoint ZIP format

A checkpoint manifest is a JSON object with `archive` (relative local ZIP path),
`archive_bytes`, `archive_sha256`, and `payload_files` (list of objects with
`path`, `bytes`, `sha256`). The ZIP must contain exactly these payloads plus
`CHECKPOINT_CONTENTS.json`, whose JSON value equals the `payload_files` list.
This is a small project format, not a standard for arbitrary ZIP archives.

`python -m cvpr3d verify-checkpoint snapshot.manifest.json` hashes the archive,
checks its member set and embedded manifest, then streams each payload. It
never extracts or executes contents. Limits: 2 GiB ZIP, 4 GiB total declared
payload, 20,000 payloads, 16 MiB manifest. Unsafe/nonportable paths, aliases,
duplicate members, symlinks and encrypted entries are rejected.

Checksums prove byte agreement with supplied metadata, not authenticity, asset
rights or scientific correctness. See [security boundaries](../SECURITY.md).
