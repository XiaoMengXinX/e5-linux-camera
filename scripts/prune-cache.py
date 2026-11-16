#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Keep one saved build cache per profile/ref within the default cache quota."""
import json
import os
import subprocess


def obsolete_caches(caches, prefix, current, ref):
    scoped = [cache for cache in caches
              if cache['key'].startswith(prefix) and cache['ref'] == ref]
    # A failed cache upload must not remove the previous useful snapshot.
    if not any(cache['key'] == current for cache in scoped):
        return []
    return [cache['id'] for cache in scoped if cache['key'] != current]


def main():
    repository = os.environ['GITHUB_REPOSITORY']
    profile = os.environ['PROFILE']
    prefix = os.environ.get('CACHE_PREFIX', f'ccache-v1-{profile}-')
    ref = os.environ['GITHUB_REF']
    pages = json.loads(subprocess.check_output([
        'gh', 'api', '--method', 'GET', '--paginate', '--slurp',
        f'/repos/{repository}/actions/caches', '-f', f'key={prefix}',
        '-f', f'ref={ref}', '-f', 'per_page=100',
    ], text=True))
    caches = [cache for page in pages for cache in page['actions_caches']]
    current = os.environ.get('CACHE_KEY') or os.environ['CCACHE_KEY']
    for cache_id in obsolete_caches(caches, prefix, current, ref):
        subprocess.run(['gh', 'api', '--method', 'DELETE',
                        f'/repos/{repository}/actions/caches/{cache_id}'], check=True)


if __name__ == '__main__':
    main()
