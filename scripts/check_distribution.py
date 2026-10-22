"""Audit exact local wheel/sdist contents, then install and test outside the checkout.

This executes reviewed local package code. It is not an untrusted-package sandbox.
"""

import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MODULES = {'cvpr3d/' + n for n in ('__init__.py', '__main__.py', 'glb.py', 'artifacts.py', 'demo.py')}
DIST_INFO = {'METADATA', 'WHEEL', 'RECORD', 'entry_points.txt', 'top_level.txt',
             'licenses/LICENSE', 'licenses/LICENSING.md', 'licenses/NOTICE.md'}
EGG_INFO = {'PKG-INFO', 'SOURCES.txt', 'dependency_links.txt', 'entry_points.txt', 'top_level.txt'}


def validate_names(names, expected):
    if len(names) != len(set(n.casefold() for n in names)) or set(names) != set(expected):
        raise ValueError(f'Unexpected distribution inventory: extra={sorted(set(names)-set(expected))}, missing={sorted(set(expected)-set(names))}')
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or '\\' in name or ':' in name or any(p in ('.', '..') for p in path.parts):
            raise ValueError(f'Unsafe member: {name}')


def verify_metadata(data, version):
    metadata = BytesParser().parsebytes(data)
    if (metadata['Name'] != 'cvpr3d-tools' or metadata['Version'] != version
            or metadata['License-Expression'] != 'MIT' or metadata.get_all('Requires-Dist')):
        raise ValueError('Unexpected package identity, license or runtime dependencies')
    if set(metadata.get_all('License-File', [])) != {'LICENSE', 'LICENSING.md', 'NOTICE.md'}:
        raise ValueError('Missing scoped license/notice metadata')


def verify_wheel(path, root=ROOT):
    version = re.search(r'^version = "([^"]+)"', (root / 'pyproject.toml').read_text(), re.M)[1]
    prefix = f'cvpr3d_tools-{version}.dist-info/'
    expected = MODULES | {prefix + name for name in DIST_INFO}
    with zipfile.ZipFile(path) as zipped:
        validate_names(zipped.namelist(), expected)
        for info in zipped.infolist():
            if info.file_size > 1024 * 1024 or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('Unexpected wheel member size/type')
        verify_metadata(zipped.read(prefix + 'METADATA'), version)
        for name in MODULES:
            if zipped.read(name) != (root / name).read_bytes():
                raise ValueError(f'Stale or changed wheel source: {name}')
        for name in ('LICENSE', 'LICENSING.md', 'NOTICE.md'):
            if zipped.read(prefix + 'licenses/' + name) != (root / name).read_bytes():
                raise ValueError(f'Wheel notice differs: {name}')
    return version


def verify_sdist(path, version, root=ROOT):
    inventory = json.loads((root / 'release-files.json').read_text())['files']
    source = {n for n in inventory if not n.startswith('.github/') and n not in ('.gitattributes', '.gitignore', 'AGENTS.md')}
    generated = {'PKG-INFO', 'setup.cfg'} | {'cvpr3d_tools.egg-info/' + n for n in EGG_INFO}
    prefix = f'cvpr3d_tools-{version}/'
    expected = {prefix + n for n in source | generated}
    with tarfile.open(path, 'r:gz') as archive:
        members = archive.getmembers()
        paths = [m.name for m in members if m.isfile()]
        validate_names(paths, expected)
        allowed_dirs = {str(parent) for name in expected for parent in PurePosixPath(name).parents}
        if len({m.name for m in members}) != len(members):
            raise ValueError('Duplicate tar members')
        for member in members:
            if not member.isfile() and not (member.isdir() and member.name in allowed_dirs):
                raise ValueError(f'Non-regular or unexpected tar member: {member.name}')
            if member.size > 1024 * 1024:
                raise ValueError('Unexpected source distribution member size')
        contents = {name[len(prefix):]: archive.extractfile(name).read() for name in paths}
    verify_metadata(contents['PKG-INFO'], version)
    for name in source:
        if contents[name] != (root / name).read_bytes():
            raise ValueError(f'Stale or changed sdist source: {name}')
    return contents


def smoke(wheel, contents):
    environment = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
    with tempfile.TemporaryDirectory(prefix='cvpr3d-release-') as directory:
        root = Path(directory)
        venv.EnvBuilder(with_pip=True).create(root / 'venv')
        binary = root / 'venv' / ('Scripts' if os.name == 'nt' else 'bin')
        python = binary / ('python.exe' if os.name == 'nt' else 'python')
        cli = binary / ('cvpr3d.exe' if os.name == 'nt' else 'cvpr3d')
        def run(args, cwd=root):
            result = subprocess.run([str(a) for a in args], cwd=cwd, env=environment,
                                    capture_output=True, text=True)
            if result.returncode:
                raise ValueError(result.stdout + result.stderr)
            return result
        run([python, '-I', '-m', 'pip', 'install', '--no-index', '--no-deps', wheel])
        run([python, '-I', '-c', 'import cvpr3d,sys; from pathlib import Path; assert Path(cvpr3d.__file__).is_relative_to(Path(sys.prefix))'])
        run([cli, '--version'])
        panel = root / 'panel.glb'
        run([python, '-I', '-m', 'cvpr3d', 'demo', panel])
        run([cli, 'compare', panel, panel, '--require-preserved'])
        source = root / 'source'
        source.mkdir()
        # All names, types and bytes were validated before writing any member.
        for name, data in contents.items():
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
        run([python, '-c', 'import cvpr3d; from pathlib import Path; assert Path(cvpr3d.__file__).resolve().is_relative_to(Path.cwd())'], source)
        result = run([python, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], source)
        return result.stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    wheels, sdists = list(args.directory.glob('*.whl')), list(args.directory.glob('*.tar.gz'))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit('Expected exactly one wheel and one sdist in a fresh output directory')
    version = verify_wheel(wheels[0])
    contents = verify_sdist(sdists[0], version)
    log = smoke(wheels[0].resolve(), contents)
    print(log, file=sys.stderr)
    print(json.dumps({'version': version, 'wheel': wheels[0].name, 'sdist': sdists[0].name,
                      'wheel_install_and_console': 'passed', 'sdist_tests': 'passed',
                      'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (wheels[0], sdists[0])}}, indent=2))


if __name__ == '__main__':
    main()
