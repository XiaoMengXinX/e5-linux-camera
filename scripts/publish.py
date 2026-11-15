#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Validate both packages, merge the retained index, then publish index last."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request

from common import MODULES, PROFILES, merge_index, sha256, validate_entry, write_json

TAG = 'modules'
RUN_MARKER = re.compile(r'<!-- camera-run:(\d+):(\d+) -->')


class GitHub:
    def __init__(self, repository, token):
        self.base = f'https://api.github.com/repos/{repository}'
        self.token = token

    def request(self, path, method='GET', data=None, missing_ok=False, raw=False):
        headers = {'Authorization': f'Bearer {self.token}',
                   'Accept': 'application/octet-stream' if raw else 'application/vnd.github+json',
                   'X-GitHub-Api-Version': '2022-11-28'}
        body = None if data is None else json.dumps(data).encode()
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.base + path, data=body,
                                         headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = response.read()
        except urllib.error.HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            raise
        return result if raw else json.loads(result)

    def assets(self, release_id):
        result = []
        page = 1
        while True:
            batch = self.request(f'/releases/{release_id}/assets?per_page=100&page={page}')
            result.extend(batch)
            if len(batch) < 100:
                return result
            page += 1


def check_freshness(api, commit, branch, run, release):
    head = api.request('/commits/' + urllib.parse.quote(branch, safe=''))['sha']
    if head != commit:
        raise ValueError('A newer driver commit exists on the publication branch')
    if release:
        match = RUN_MARKER.search(release['body'] or '')
        if not match:
            raise ValueError('Existing release has no publisher run marker; review before adopting it')
        if run < tuple(map(int, match.groups())):
            raise ValueError('A newer workflow has already published this release')


def read_packages(dist):
    entries = []
    for profile in PROFILES:
        entry = json.loads((dist / f'{profile}.json').read_text())
        validate_entry(entry)
        if entry['profile'] != profile:
            raise ValueError('Profile metadata filename does not match its entry')
        archive = dist / entry['asset']
        if sha256(archive) != entry['sha256']:
            raise ValueError('Archive checksum mismatch')
        with tarfile.open(archive, 'r:gz') as tar:
            expected = {'manifest.json', *(f'modules/{name}' for name in MODULES)}
            members = tar.getmembers()
            if len(members) != len(expected) or {m.name for m in members} != expected:
                raise ValueError('Unexpected archive layout')
            if not all(member.isfile() for member in members):
                raise ValueError('Archive contains a non-file member')
            inner = json.load(tar.extractfile('manifest.json'))
            expected_inner = dict(entry, schema=1)
            del expected_inner['sha256']
            if inner != expected_inner:
                raise ValueError('Package manifest differs from index entry')
            for name in MODULES:
                with tar.extractfile(f'modules/{name}') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if digest != entry['modules'][name]:
                    raise ValueError(f'{name}: package checksum mismatch')
        entries.append(entry)
    for field in ('driver_commit', 'board_commit', 'kernel_commit'):
        if len({entry[field] for entry in entries}) != 1:
            raise ValueError(f'Profiles were built from different {field}')
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, default=Path('dist'))
    parser.add_argument('--snapshot', type=Path, help='Require the resolve job source snapshot')
    args = parser.parse_args()
    dist = args.dist.resolve()
    entries = read_packages(dist)
    if args.snapshot:
        expected = json.loads(args.snapshot.read_text())
        for entry in entries:
            if any(entry[field] != expected[field]
                   for field in ('driver_commit', 'board_commit', 'kernel_commit')):
                raise ValueError('Artifacts differ from the resolve job source snapshot')
    commit = os.environ['GITHUB_SHA']
    if any(entry['driver_commit'] != commit for entry in entries):
        raise ValueError('Artifacts do not belong to this workflow commit')
    run = (int(os.environ['GITHUB_RUN_ID']), int(os.environ['GITHUB_RUN_ATTEMPT']))
    repository = os.environ['GITHUB_REPOSITORY']
    branch = os.environ['GITHUB_REF_NAME']
    api = GitHub(repository, os.environ['GH_TOKEN'])
    if branch != api.request('')['default_branch']:
        raise ValueError('Only the default branch can publish the modules release')
    release = api.request(f'/releases/tags/{TAG}', missing_ok=True)
    check_freshness(api, commit, branch, run, release)
    previous = {'schema': 1, 'builds': []}
    assets = {}
    if release:
        assets = {asset['name']: asset for asset in api.assets(release['id'])}
        if 'manifest.json' in assets:
            previous = json.loads(api.request(
                f"/releases/assets/{assets['manifest.json']['id']}", raw=True))
        elif not release['draft']:
            raise ValueError('Published release is missing manifest.json')
    merged = merge_index(previous, entries)
    current_assets = {entry['asset'] for entry in entries}
    for entry in merged['builds']:
        if entry['asset'] not in current_assets and entry['asset'] not in assets:
            raise ValueError(f"Retained asset missing: {entry['asset']}")
    write_json(dist / 'manifest.json', merged)
    body = ('Camera modules for e5, lym10k and t512n. '
            'Use manifest.json to select the matching profile and kernel release.\n\n'
            f'<!-- camera-run:{run[0]}:{run[1]} -->')
    if release is None:
        release = api.request('/releases', method='POST', data={
            'tag_name': TAG, 'target_commitish': commit, 'name': 'Camera modules',
            'body': body, 'draft': True, 'prerelease': False,
        })
    # All validation precedes the first upload. The global index is replaced last.
    for entry in entries:
        subprocess.run(['gh', 'release', 'upload', TAG, str(dist / entry['asset']),
                        '--clobber', '--repo', repository], check=True)
    # Recheck branch freshness after potentially slow uploads.
    check_freshness(api, commit, branch, run, release)
    subprocess.run(['gh', 'release', 'upload', TAG, str(dist / 'manifest.json'),
                    '--clobber', '--repo', repository], check=True)
    api.request(f"/releases/{release['id']}", method='PATCH', data={
        'name': 'Camera modules', 'body': body, 'draft': False,
    })


if __name__ == '__main__':
    main()
