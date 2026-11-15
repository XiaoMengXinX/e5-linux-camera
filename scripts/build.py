#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build a complete profile kernel and package its external camera modules."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

from common import MODULES, PROFILES, config_sha256, sha256, validate_entry, write_json


def run(command):
    subprocess.run([str(item) for item in command], check=True)


def output(command):
    return subprocess.check_output([str(item) for item in command], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=PROFILES)
    parser.add_argument('--work', type=Path, default=Path('work'))
    parser.add_argument('--dist', type=Path, default=Path('dist'))
    parser.add_argument('--jobs', type=int, default=os.cpu_count())
    parser.add_argument('--configure-only', action='store_true',
                        help='Apply upstream board preparation and validate olddefconfig only')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    work, dist = args.work.resolve(), args.dist.resolve()
    inputs = json.loads((work / 'inputs.json').read_text())
    toolchain = output(['clang-18', '--version'])
    if 'clang version 18.' not in toolchain:
        raise ValueError('LLVM18 is required')
    kernel = work / f'kernel-{args.profile}'
    objects = work / f'objects-{args.profile}'
    run(['git', '-C', work / 'linux', 'worktree', 'add', '--detach', kernel,
         inputs['kernel_commit']])
    run([sys.executable, work / 'board/devices' / args.profile / 'prepare-kernel.py', kernel])
    objects.mkdir()
    config = objects / '.config'
    shutil.copyfile(root / 'configs' / f'{args.profile}.config', config)
    make = ['make', '--no-print-directory', '-C', kernel, f'O={objects}', 'ARCH=arm64', 'LLVM=-18',
            'LOCALVERSION=', f'-j{args.jobs}']
    run(make + ['olddefconfig'])
    config_text = config.read_text()
    compat = 'CONFIG_COMPAT=y' if args.profile == 'lym10k' else '# CONFIG_COMPAT is not set'
    if compat not in config_text.splitlines():
        raise ValueError('olddefconfig changed the profile CONFIG_COMPAT contract')
    release = output(make + ['-s', 'kernelrelease'])
    if not re.fullmatch(r'[A-Za-z0-9_.+-]+', release):
        raise ValueError(f'Invalid kernel release: {release}')
    entry = dict(inputs, profile=args.profile, kernel_release=release,
                 config_sha256=config_sha256(config),
                 asset=f'sprd-camera-{args.profile}-{release}-arm64.tar.gz')
    metadata = dict(entry, input_config_sha256=sha256(root / 'configs' / f'{args.profile}.config'),
                    clang=toolchain, lld=output(['ld.lld-18', '--version']),
                    pahole=output(['pahole', '--version']))
    write_json(objects / 'build-inputs.json', metadata)
    if args.configure_only:
        print(json.dumps(metadata, indent=2))
        return
    run(make + ['modules_prepare'])
    run(make + ['vmlinux', 'modules'])
    if not (objects / 'Module.symvers').stat().st_size:
        raise ValueError('Full kernel build did not produce Module.symvers')
    source = work / f'camera-{args.profile}'
    shutil.copytree(root / 'source/camera', source)
    run(make + [f'M={source / "sensor"}', 'modules'])
    # flash Kbuild derives filenames from wildcard *.c. Keep generated .mod.c
    # in a separate MO tree, as in the verified module port.
    flash_output = work / f'flash-{args.profile}'
    run(make + [f'M={source / "flash/flash_drv"}', f'MO={flash_output}', 'modules'])
    symbols = f'{source / "sensor/Module.symvers"} {flash_output / "Module.symvers"}'
    run(make + [f'M={source / "cam_sys"}',
                'BSP_BOARD_CAMERA_MODULE_ISP_ADAPT_VERSION=qogirn6l',
                'BSP_BOARD_CAMERA_MODULE_CSI_VERSION=receiver_r3p2',
                f'KBUILD_EXTRA_SYMBOLS={symbols}', 'modules'])
    package = work / f'package-{args.profile}'
    (package / 'modules').mkdir(parents=True)
    locations = [source / 'sensor', flash_output, source / 'cam_sys']
    hashes = {}
    for name, location in zip(MODULES, locations):
        destination = package / 'modules' / name
        shutil.copyfile(location / name, destination)
        run(['llvm-objcopy-18', '--strip-debug', '--remove-section=.BTF',
             '--remove-section=.BTF.ext', destination])
        vermagic = output(['modinfo', '-F', 'vermagic', destination])
        if vermagic.split()[0] != release:
            raise ValueError(f'{name}: vermagic differs from kernel release')
        sections = output(['llvm-readelf-18', '--sections', destination])
        if '.debug_' in sections or '.BTF' in sections:
            raise ValueError(f'{name}: debug/BTF sections remain')
        hashes[name] = sha256(destination)
    entry['modules'] = hashes
    validate_entry(entry, archive=False)
    write_json(package / 'manifest.json', dict(entry, schema=1))
    dist.mkdir(parents=True, exist_ok=True)
    archive = dist / entry['asset']
    with tarfile.open(archive, 'w:gz') as tar:
        for path in sorted(package.rglob('*')):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(package)), recursive=False)
    entry['sha256'] = sha256(archive)
    write_json(dist / f'{args.profile}.json', entry)
    # Effective config and provenance are CI artifacts, separate from the runtime package.
    shutil.copyfile(config, dist / f'{args.profile}.config')
    shutil.copyfile(objects / 'build-inputs.json', dist / f'{args.profile}-inputs.json')


if __name__ == '__main__':
    main()
