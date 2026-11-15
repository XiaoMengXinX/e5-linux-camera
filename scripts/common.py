#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Shared config fingerprint and release index contract."""
import hashlib
import json
import re
from pathlib import Path

PROFILES = ('e5', 'lym10k', 't512n')
MODULES = ('sprd_sensor.ko', 'sprd_flash_drv.ko', 'sprd_camera.ko')
TOOLCHAIN_METADATA = {
    'CONFIG_CC_VERSION_TEXT', 'CONFIG_CLANG_VERSION', 'CONFIG_LLD_VERSION',
    'CONFIG_GCC_VERSION', 'CONFIG_AS_VERSION', 'CONFIG_LD_VERSION',
    'CONFIG_PAHOLE_VERSION',
}


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def config_sha256(path):
    lines = sorted(line for line in Path(path).read_text().splitlines()
                   if re.fullmatch(r'CONFIG_[A-Za-z0-9_]+=.*', line)
                   and line.split('=', 1)[0] not in TOOLCHAIN_METADATA)
    return hashlib.sha256(('\n'.join(lines) + '\n').encode()).hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def validate_entry(entry, archive=True):
    if entry['profile'] not in PROFILES:
        raise ValueError('Unsupported profile in manifest')
    release = entry['kernel_release']
    if not re.fullmatch(r'[A-Za-z0-9_.+-]+', release):
        raise ValueError('Invalid kernel release')
    expected = f"sprd-camera-{entry['profile']}-{release}-arm64.tar.gz"
    if entry['asset'] != expected:
        raise ValueError('Asset name differs from profile/kernel release')
    if set(entry['modules']) != set(MODULES):
        raise ValueError('Manifest must describe exactly three modules')
    hashes = [entry['config_sha256'], *entry['modules'].values()]
    if archive:
        hashes.append(entry['sha256'])
    if not all(re.fullmatch(r'[0-9a-f]{64}', value) for value in hashes):
        raise ValueError('Invalid SHA256')
    if not all(re.fullmatch(r'[0-9a-f]{40}', entry[name])
               for name in ('driver_commit', 'kernel_commit', 'board_commit')):
        raise ValueError('Invalid source commit')


def merge_index(previous, entries):
    if previous['schema'] != 1:
        raise ValueError('Unsupported release index schema')
    merged = {}
    for entry in previous['builds']:
        validate_entry(entry)
        key = (entry['profile'], entry['kernel_release'])
        if key in merged:
            raise ValueError('Duplicate key in previous index')
        merged[key] = entry
    current_keys = set()
    for entry in entries:
        validate_entry(entry)
        key = (entry['profile'], entry['kernel_release'])
        if key in current_keys:
            raise ValueError('Duplicate build key')
        current_keys.add(key)
        merged[key] = entry
    return {'schema': 1, 'builds': [merged[key] for key in sorted(merged)]}
