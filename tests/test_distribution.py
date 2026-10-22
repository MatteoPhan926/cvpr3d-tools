"""Guard against accidental artifact inclusion in a release."""

import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('distribution_checks', Path(__file__).resolve().parents[1] / 'scripts/check_distribution.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


class DistributionTests(unittest.TestCase):
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
