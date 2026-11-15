# SPDX-License-Identifier: GPL-2.0-only
"""Exact kernel build cache identity and restored object validation."""
import hashlib
import json
from pathlib import Path

from common import config_sha256, sha256, write_json

REQUIRED_FILES = (
    'vmlinux', 'Module.symvers', '.config', 'include/config/kernel.release',
    'include/config/auto.conf', 'include/generated/autoconf.h',
    'scripts/mod/modpost', 'scripts/basic/fixdep',
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def cache_key(recipe):
    return f"kernel-v1-{recipe['profile']}-{digest(recipe)}"


def record_kernel(objects, recipe):
    for name in REQUIRED_FILES:
        if not (objects / name).stat().st_size:
            raise ValueError(f'Kernel cache file is empty: {name}')
    if sha256(objects / '.config') != recipe['effective_config_sha256']:
        raise ValueError('Kernel build changed the effective config')
    # Large object files are preserved by actions/cache; checksum the ABI inputs
    # and vmlinux as well, before accepting a restored build for external modules.
    write_json(objects / 'kernel-cache.json', {
        'recipe': recipe,
        'files': {name: sha256(objects / name) for name in REQUIRED_FILES},
    })


def validate_kernel(objects, recipe):
    saved = json.loads((objects / 'kernel-cache.json').read_text())
    if saved['recipe'] != recipe:
        raise ValueError('Kernel cache provenance mismatch')
    if set(saved['files']) != set(REQUIRED_FILES):
        raise ValueError('Kernel cache is incomplete')
    for name, expected in saved['files'].items():
        if sha256(objects / name) != expected:
            raise ValueError(f'Kernel cache checksum mismatch: {name}')
    if sha256(objects / '.config') != recipe['effective_config_sha256']:
        raise ValueError('Cached config differs from fresh olddefconfig')
    if config_sha256(objects / '.config') != recipe['config_sha256']:
        raise ValueError('Cached config fingerprint mismatch')
    if (objects / 'include/config/kernel.release').read_text().strip() != recipe['kernel_release']:
        raise ValueError('Cached kernel release mismatch')
