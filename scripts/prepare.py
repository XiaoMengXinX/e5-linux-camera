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
    parser.add_argument('--board-ref', default='main', help='Board branch or fixed commit')
    parser.add_argument('--snapshot', type=Path, help='Use the resolve job inputs.json snapshot')
    parser.add_argument('--resolve-only', action='store_true', help='Resolve board and baseline without fetching Linux')
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    board = work / 'board'
    kernel = work / 'linux'
    root = Path(__file__).resolve().parents[1]
    expected = json.loads(args.snapshot.read_text()) if args.snapshot else None
    driver_commit = revision(root)
    if expected and expected['driver_commit'] != driver_commit:
        raise ValueError('Snapshot belongs to a different driver commit')
    board_ref = expected['board_commit'] if expected else args.board_ref
    run('git', 'init', str(board))
    run('git', '-C', str(board), 'remote', 'add', 'origin',
        'https://github.com/sprd-linux-devs/e5-linux.git')
    run('git', '-C', str(board), 'fetch', '--depth=1', 'origin', board_ref)
    run('git', '-C', str(board), 'checkout', '--detach', 'FETCH_HEAD')
    layout = json.loads((board / 'tools/build-layout.json').read_text())
    baseline = layout['local_kernel_build']['revision']
    if not re.fullmatch(r'[0-9a-f]{40}', baseline):
        raise ValueError('Expected a fixed 40-character Linux commit')
    for profile in PROFILES:
        if profile not in layout['profiles']:
            raise ValueError(f'Upstream layout has no {profile} profile')
        if not (board / 'devices' / profile / 'prepare-kernel.py').is_file():
            raise FileNotFoundError(f'Missing prepare-kernel.py for {profile}')
    inputs = {'driver_commit': driver_commit, 'board_commit': revision(board),
              'kernel_commit': baseline}
    if expected and inputs != expected:
        raise ValueError('Resolved board/kernel differs from the requested snapshot')
    write_json(work / 'inputs.json', inputs)
    if args.resolve_only:
        return
    run('git', 'init', str(kernel))
    run('git', '-C', str(kernel), 'remote', 'add', 'origin',
        'https://github.com/sprd-linux-devs/linux.git')
    run('git', '-C', str(kernel), 'fetch', '--depth=1', 'origin', baseline)
    run('git', '-C', str(kernel), 'checkout', '--detach', 'FETCH_HEAD')
    if revision(kernel) != baseline:
        raise ValueError('Fetched kernel differs from layout baseline')


if __name__ == '__main__':
    main()
