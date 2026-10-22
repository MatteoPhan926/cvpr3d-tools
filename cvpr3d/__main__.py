"""Offline command line interface. Reports never overwrite an existing file."""

import argparse
import json
import sys
import zipfile
from pathlib import Path

from . import __version__
from .artifacts import verify_checkpoint, verify_files
from .demo import generate_demo
from .glb import compare_glbs, inspect_glb


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="Describe GLB structure and embedded image hashes")
    inspect.add_argument("input", type=Path)
    compare = sub.add_parser("compare", help="Compare materials and embedded image bytes only")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    compare.add_argument("--require-preserved", action="store_true", help="Exit 1 for different or unsupported comparisons")
    demo = sub.add_parser("demo", help="Write a synthetic animated panel, with no third-party assets")
    demo.add_argument("path", type=Path)
    checkpoint = sub.add_parser("verify-checkpoint", help="Verify a local checkpoint ZIP without extraction")
    checkpoint.add_argument("manifest", type=Path)
    files = sub.add_parser("verify-files", help="Verify a path -> {bytes, sha256} file manifest")
    files.add_argument("manifest", type=Path)
    files.add_argument("--root", type=Path)
    for child in (inspect, compare, checkpoint, files):
        child.add_argument("--output", type=Path, help="Create a JSON report; refuses existing files")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            generate_demo(args.path)
            result = inspect_glb(args.path)
        elif args.command == "inspect":
            result = inspect_glb(args.input)
        elif args.command == "compare":
            result = compare_glbs(args.before, args.after)
        elif args.command == "verify-checkpoint":
            result = verify_checkpoint(args.manifest)
        else:
            result = verify_files(args.manifest, args.root)
        payload = json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
        output = getattr(args, "output", None)
        if output:
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
        else:
            print(payload, end="")
        if result.get("ok") is False:
            return 1
        if getattr(args, "require_preserved", False) and result.get("preserved") is not True:
            return 1
        return 0
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, RecursionError) as exc:
        print(f"cvpr3d: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
