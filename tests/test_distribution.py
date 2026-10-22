"""Guard against accidental artifact inclusion in a release."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('distribution_checks', Path(__file__).resolve().parents[1] / 'scripts/check_distribution.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


class DistributionTests(unittest.TestCase):
    def probe_import(self, expected, cwd, optimized=False):
        environment = {k: v for k, v in os.environ.items()
                       if k not in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSAFEPATH')}
        return subprocess.run(
            [sys.executable, '-S', *(['-O'] if optimized else []),
             '-c', checks.IMPORT_ORIGIN_CHECK, str(expected)],
            cwd=cwd, env=environment, capture_output=True, text=True)

    def make_package(self, root):
        package = root / 'cvpr3d'
        package.mkdir(parents=True)
        (package / '__init__.py').write_text('', encoding='utf-8')
        return package

    def test_import_origin_rejects_other_install_even_when_optimized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / 'source'
            expected.mkdir()
            other = root / 'source-other' / 'site-packages'
            self.make_package(other)
            for optimized in (False, True):
                with self.subTest(optimized=optimized):
                    accepted = self.probe_import(other, other, optimized)
                    self.assertEqual(accepted.returncode, 0, accepted.stderr)
                    rejected = self.probe_import(expected, other, optimized)
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertIn('expected a file under', rejected.stderr)

    def test_import_origin_resolves_directory_alias(self):
        with tempfile.TemporaryDirectory(prefix='cvpr3d import alias ') as directory:
            root = Path(directory).resolve()
            source = root / 'long source directory'
            self.make_package(source)
            if os.name == 'nt':
                import ctypes
                get_short = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
                get_short.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
                get_short.restype = ctypes.c_uint32
                buffer = ctypes.create_unicode_buffer(32768)
                size = get_short(str(source), buffer, len(buffer))
                if not size or size >= len(buffer):
                    self.fail('GetShortPathNameW failed for the existing fixture')
                alias = Path(buffer.value)
                if alias == source:
                    self.skipTest('8.3 aliases are unavailable on this volume')
            else:
                alias = root / 'alias'
                alias.symlink_to(source, target_is_directory=True)
            self.assertEqual(alias.resolve(), source)
            result = self.probe_import(alias, alias)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_import_origin_rejects_package_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.mkdir()
            outside_package = self.make_package(root / 'outside')
            try:
                (source / 'cvpr3d').symlink_to(outside_package, target_is_directory=True)
            except OSError:
                self.skipTest('Symlink creation unavailable on this host')
            result = self.probe_import(source, source)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('expected a file under', result.stderr)

    def test_extra_python_or_asset_is_rejected(self):
        expected = ['cvpr3d/glb.py', 'LICENSE']
        for extra in ('historical/asset.glb', 'cvpr3d/unreviewed.py', '../escape', 'LICENSE'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                checks.validate_names(expected + [extra], expected)

    def test_missing_or_case_colliding_files_are_rejected(self):
        with self.assertRaises(ValueError):
            checks.validate_names(['LICENSE'], ['LICENSE', 'README.md'])
        with self.assertRaises(ValueError):
            checks.validate_names(['LICENSE', 'license'], ['LICENSE', 'license'])

    def test_exact_inventory_is_accepted(self):
        checks.validate_names(['LICENSE', 'cvpr3d/glb.py'], ['cvpr3d/glb.py', 'LICENSE'])

    def test_runtime_dependency_or_changed_license_is_rejected(self):
        fields = 'Name: cvpr3d-tools\nVersion: 0.1.0\nLicense-Expression: MIT\nLicense-File: LICENSE\nLicense-File: LICENSING.md\nLicense-File: NOTICE.md\n'
        checks.verify_metadata(fields.encode(), '0.1.0')
        for altered in (fields + 'Requires-Dist: torch\n', fields.replace('MIT', 'BSD-3-Clause')):
            with self.assertRaises(ValueError):
                checks.verify_metadata(altered.encode(), '0.1.0')
