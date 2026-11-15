# SPDX-License-Identifier: GPL-2.0-only
import copy
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from common import MODULES, PROFILES, config_sha256, merge_index, sha256, write_json
from publish import check_freshness, read_packages


def entry(profile='lym10k', release='6.18.54-lym10k-bringup1'):
    return dict(profile=profile, kernel_release=release,
                asset=f'sprd-camera-{profile}-{release}-arm64.tar.gz',
                sha256='a' * 64, config_sha256='b' * 64,
                modules={name: 'c' * 64 for name in MODULES},
                driver_commit='d' * 40, kernel_commit='e' * 40, board_commit='f' * 40)


class ReleaseContract(unittest.TestCase):
    def test_config_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.config'
            path.write_text('# header\nCONFIG_Z="x y"\nCONFIG_CC_VERSION_TEXT="clang"\n'
                            'CONFIG_COMPAT=y\n# CONFIG_UNUSED is not set\nCONFIG_CLANG_VERSION=180108\n')
            expected = hashlib.sha256(b'CONFIG_COMPAT=y\nCONFIG_Z="x y"\n').hexdigest()
            self.assertEqual(config_sha256(path), expected)
            path.write_text('CONFIG_Z="x y"\n# CONFIG_COMPAT is not set\n')
            self.assertNotEqual(config_sha256(path), expected)

    def test_merge_preserves_other_releases_and_replaces_same_key(self):
        old = entry()
        other = entry(release='6.18.53-lym10k-bringup1')
        new = dict(old, sha256='1' * 64)
        previous = {'schema': 1, 'builds': [old, other]}
        result = merge_index(previous, [new])
        self.assertEqual(result['builds'], [other, new])
        self.assertEqual(previous['builds'][0], old)

    def test_merge_rejects_duplicate_previous_keys(self):
        with self.assertRaises(ValueError):
            merge_index({'schema': 1, 'builds': [entry(), entry()]}, [])

    def test_old_run_cannot_overwrite_new_publication(self):
        class API:
            def request(self, path):
                return {'sha': 'd' * 40}
        release = {'body': '<!-- camera-run:20:2 -->'}
        for run in [(19, 9), (20, 1)]:
            with self.assertRaises(ValueError):
                check_freshness(API(), 'd' * 40, 'main', run, release)
        check_freshness(API(), 'd' * 40, 'main', (21, 1), release)
        with self.assertRaises(ValueError):
            check_freshness(API(), '1' * 40, 'main', (21, 1), release)

    def test_packages_validate_layout_and_hashes_before_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory)
            for profile in PROFILES:
                data = entry(profile=profile, release=f'6.18.54-{profile}-bringup1')
                package = dist / profile
                (package / 'modules').mkdir(parents=True)
                for name in MODULES:
                    (package / 'modules' / name).write_bytes(name.encode())
                    data['modules'][name] = sha256(package / 'modules' / name)
                inner = dict(data, schema=1)
                del inner['sha256']
                write_json(package / 'manifest.json', inner)
                with tarfile.open(dist / data['asset'], 'w:gz') as tar:
                    for file in sorted(package.rglob('*')):
                        if file.is_file():
                            tar.add(file, arcname=str(file.relative_to(package)))
                data['sha256'] = sha256(dist / data['asset'])
                write_json(dist / f'{profile}.json', data)
            self.assertEqual(len(read_packages(dist)), 2)
            path = dist / 't512n.json'
            damaged = json.loads(path.read_text())
            damaged['sha256'] = '0' * 64
            write_json(path, damaged)
            with self.assertRaises(ValueError):
                read_packages(dist)


if __name__ == '__main__':
    unittest.main()
