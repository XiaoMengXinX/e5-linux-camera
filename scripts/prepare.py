#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Resolve upstream main once and fetch its fixed Linux baseline."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from common import PROFILES, write_json


def run(*command):
    subprocess.run(command, check=True)


def revision(repo):
    return subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'],
                                   text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=Path('work'))
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    board = work / 'board'
    kernel = work / 'linux'
    run('git', 'clone', '--depth=1', '--branch=main',
        'https://github.com/sprd-linux-devs/e5-linux.git', str(board))
    layout = json.loads((board / 'tools/build-layout.json').read_text())
    baseline = layout['local_kernel_build']['revision']
    if not re.fullmatch(r'[0-9a-f]{40}', baseline):
        raise ValueError('Expected a fixed 40-character Linux commit')
    for profile in PROFILES:
        if profile not in layout['profiles']:
            raise ValueError(f'Upstream layout has no {profile} profile')
        if not (board / 'devices' / profile / 'prepare-kernel.py').is_file():
            raise FileNotFoundError(f'Missing prepare-kernel.py for {profile}')
    run('git', 'init', str(kernel))
    run('git', '-C', str(kernel), 'remote', 'add', 'origin',
        'https://github.com/sprd-linux-devs/linux.git')
    run('git', '-C', str(kernel), 'fetch', '--depth=1', 'origin', baseline)
    run('git', '-C', str(kernel), 'checkout', '--detach', 'FETCH_HEAD')
    if revision(kernel) != baseline:
        raise ValueError('Fetched kernel differs from layout baseline')
    root = Path(__file__).resolve().parents[1]
    write_json(work / 'inputs.json', {
        'driver_commit': revision(root), 'board_commit': revision(board),
        'kernel_commit': baseline,
    })


if __name__ == '__main__':
    main()
