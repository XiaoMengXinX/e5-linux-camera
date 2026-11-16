# SPDX-License-Identifier: GPL-2.0-only
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build import build_package_versions, normalize_source_mtimes, prepare_kernel_objects, verify_running_config
from common import config_sha256, sha256
from kernel_cache import REQUIRED_FILES, cache_key, record_kernel, validate_kernel

spec = importlib.util.spec_from_file_location(
    'prune_cache', Path(__file__).resolve().parents[1] / 'scripts/prune-cache.py')
prune_cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prune_cache)


class KernelCache(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.objects = self.root / 'objects'
        for name in REQUIRED_FILES:
            path = self.objects / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'{name}\n')
        config = self.objects / '.config'
        config.write_text('CONFIG_COMPAT=y\nCONFIG_LOCALVERSION="-lym10k-bringup1"\n')
        (self.objects / 'include/config/kernel.release').write_text('6.18.54-lym10k-bringup1\n')
        self.recipe = dict(profile='lym10k', kernel_commit='a' * 40, board_commit='b' * 40,
                           input_config_sha256='c' * 64,
                           effective_config_sha256=sha256(config), config_sha256=config_sha256(config),
                           kernel_release='6.18.54-lym10k-bringup1',
                           toolchain={'clang': '18.1.3', 'pahole': '1.25'},
                           scripts={'build.py': 'd' * 64}, timestamp='fixed',
                           kernel_path='/kernel', objects_path='/objects')

    def test_effective_config_matches_running_kernel_before_build(self):
        reference = self.root / 'running.config'
        effective = self.root / 'effective.config'
        reference.write_text('CONFIG_RUSTC_VERSION=0\nCONFIG_COMPAT=y\nCONFIG_CLANG_VERSION=180108\n')
        effective.write_text('CONFIG_COMPAT=y\nCONFIG_RUSTC_VERSION=0\nCONFIG_CLANG_VERSION=180103\n')
        verify_running_config(reference, effective)
        effective.write_text('CONFIG_COMPAT=y\nCONFIG_RUSTC_VERSION=109901\nCONFIG_RUSTC_HAS_COERCE_POINTEE=y\n')
        with self.assertRaisesRegex(ValueError, 'RUSTC_HAS_COERCE_POINTEE'):
            verify_running_config(reference, effective)

    def test_key_covers_profile_source_configs_tools_scripts_and_paths(self):
        baseline = cache_key(self.recipe)
        for field, value in (
            ('profile', 't512n'), ('kernel_commit', 'e' * 40), ('board_commit', 'f' * 40),
            ('input_config_sha256', '0' * 64), ('effective_config_sha256', '1' * 64),
            ('toolchain', {'clang': '18.1.3', 'pahole': '1.26'}),
            ('scripts', {'build.py': '2' * 64}), ('kernel_path', '/new-kernel'),
        ):
            with self.subTest(field=field):
                changed = dict(self.recipe, **{field: value})
                self.assertNotEqual(cache_key(changed), baseline)

    def test_toolchain_packages_include_build_libraries_and_exclude_unrelated_runner_tools(self):
        rows = ('clang-18=18.1.3\nlibelf1t64:arm64=0.190\nlibllvm18:arm64=18.1.3\n'
                'dotnet-sdk-8.0=8.0.1\ngoogle-chrome-stable=140\n')
        with patch('build.output', return_value=rows):
            self.assertEqual(build_package_versions(),
                             ['clang-18=18.1.3', 'libelf1t64:arm64=0.190', 'libllvm18:arm64=18.1.3'])

    def test_exact_hit_validates_without_invoking_make(self):
        record_kernel(self.objects, self.recipe)
        with patch('build.run') as make:
            prepare_kernel_objects(['make'], self.objects, self.root / 'candidate', self.recipe, True)
        make.assert_not_called()

    def test_hit_rejects_other_profile_or_compat_without_fallback(self):
        record_kernel(self.objects, self.recipe)
        with patch('build.run') as make:
            with self.assertRaisesRegex(ValueError, 'provenance'):
                prepare_kernel_objects(['make'], self.objects, self.root / 'candidate',
                                       dict(self.recipe, profile='t512n'), True)
            (self.objects / '.config').write_text('# CONFIG_COMPAT is not set\n')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                prepare_kernel_objects(['make'], self.objects, self.root / 'candidate', self.recipe, True)
        make.assert_not_called()

    def test_hit_rejects_missing_or_corrupt_kernel_outputs(self):
        record_kernel(self.objects, self.recipe)
        (self.objects / 'Module.symvers').write_text('corrupt\n')
        with self.assertRaisesRegex(ValueError, 'Module.symvers'):
            validate_kernel(self.objects, self.recipe)
        (self.objects / 'Module.symvers').write_text('Module.symvers\n')
        (self.objects / 'vmlinux').unlink()
        with self.assertRaises(FileNotFoundError):
            validate_kernel(self.objects, self.recipe)

    def test_miss_builds_kernel_then_records_provenance(self):
        fresh = self.root / 'fresh'
        candidate = self.root / 'candidate'
        candidate.mkdir()
        (candidate / '.config').write_bytes((self.objects / '.config').read_bytes())
        with patch('build.run') as make, patch('build.record_kernel') as record:
            prepare_kernel_objects(['make'], fresh, candidate, self.recipe, False)
        self.assertEqual([call.args[0] for call in make.call_args_list],
                         [['make', 'modules_prepare'], ['make', 'vmlinux', 'modules']])
        record.assert_called_once_with(fresh, self.recipe)
        self.assertEqual((fresh / '.config').read_bytes(), (candidate / '.config').read_bytes())

    def test_new_checkout_mtimes_do_not_invalidate_saved_outputs(self):
        kernel = self.root / 'kernel'
        kernel.mkdir()
        kconfig = kernel / 'Kconfig'
        kconfig.write_text('config COMPAT\n')
        gitfile = kernel / '.git'
        gitfile.write_text('gitdir: elsewhere\n')
        git_mtime = gitfile.stat().st_mtime_ns
        normalize_source_mtimes(kernel, 100)
        self.assertEqual(kconfig.stat().st_mtime, 100)
        self.assertLess(kconfig.stat().st_mtime, (self.objects / 'include/config/auto.conf').stat().st_mtime)
        self.assertEqual(gitfile.stat().st_mtime_ns, git_mtime)

    def test_ccache_retains_prior_snapshot_until_new_upload_exists(self):
        prefix = 'ccache-v1-lym10k-'
        ref = 'refs/heads/main'
        old = {'id': 1, 'key': prefix + 'old', 'ref': ref}
        current = {'id': 2, 'key': prefix + 'current', 'ref': ref}
        other = {'id': 3, 'key': 'ccache-v1-t512n-old', 'ref': ref}
        branch = {'id': 4, 'key': prefix + 'branch', 'ref': 'refs/heads/dev'}
        self.assertEqual(prune_cache.obsolete_caches([old], prefix, current['key'], ref), [])
        self.assertEqual(prune_cache.obsolete_caches([old, current, other, branch],
                                                     prefix, current['key'], ref), [1])


if __name__ == '__main__':
    unittest.main()
