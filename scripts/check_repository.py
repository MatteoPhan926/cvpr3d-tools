"""Check the exact publication inventory, local Markdown links and import receipt."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-import', action='store_true', help='Check initial imported bytes; not a constraint on future edits')
    args = parser.parse_args()
    expected = json.loads((ROOT / 'release-files.json').read_text(encoding='utf-8'))['files']
    if len(expected) != len(set(expected)):
        raise SystemExit('Duplicate publication allowlist entry')
    if (ROOT / '.git').exists():
        actual = set(subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z']).decode().split('\0')) - {''}
    else:
        actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()
                  and not any(part in ('__pycache__', 'dist', 'build', '.venv', 'outputs')
                              or part.endswith('.egg-info') for part in p.relative_to(ROOT).parts)}
    if actual != set(expected):
        raise SystemExit(f'Publication file mismatch; extra={sorted(actual-set(expected))}; missing={sorted(set(expected)-actual)}')
    links = 0
    for name in expected:
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            raise SystemExit(f'Non-regular or missing file: {name}')
        if path.suffix == '.md':
            for target in re.findall(r'\]\(([^\s)]+)\)', path.read_text(encoding='utf-8')):
                target = unquote(target.split('#', 1)[0])
                if not target or '://' in target or target.startswith('mailto:'):
                    continue
                if not (path.parent / target).is_file():
                    raise SystemExit(f'Broken local link in {name}: {target}')
                links += 1
    if args.verify_import:
        receipt = json.loads((ROOT / 'SOURCE_PROVENANCE.json').read_text(encoding='utf-8'))
        for name, row in receipt['files'].items():
            if name not in expected or hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != row['sha256']:
                raise SystemExit(f'Initial import differs: {name}')
    print(json.dumps({'files': len(actual), 'local_links': links, 'import_hashes_checked': args.verify_import}))


if __name__ == '__main__':
    main()
