#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build a complete profile kernel and package its external camera modules."""
import argparse
import difflib
import json
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

from common import MODULES, PROFILES, TOOLCHAIN_METADATA, config_sha256, sha256, validate_entry, write_json
from kernel_cache import cache_key, digest, record_kernel, validate_kernel


def run(command):
    subprocess.run([str(item) for item in command], check=True)


def output(command):
    return subprocess.check_output([str(item) for item in command], text=True).strip()


def verify_running_config(reference, effective):
    if config_sha256(reference) == config_sha256(effective):
        return

    def lines(path):
        return sorted(line + '\n' for line in path.read_text().splitlines()
                      if re.fullmatch(r'CONFIG_[A-Za-z0-9_]+=.*', line)
                      and line.split('=', 1)[0] not in TOOLCHAIN_METADATA)

    difference = ''.join(difflib.unified_diff(
        lines(reference), lines(effective), fromfile=str(reference), tofile=str(effective)))
    raise ValueError('olddefconfig differs from the running kernel config:\n' + difference)


def build_package_versions():
    tools = {'clang-18', 'lld-18', 'llvm-18', 'llvm-18-runtime', 'llvm-18-linker-tools',
             'make', 'bison', 'flex', 'bc', 'dwarves', 'pahole', 'ccache',
             'libssl-dev', 'libelf-dev', 'libncurses-dev', 'zstd', 'xz-utils'}
    prefixes = ('gcc', 'g++', 'cpp', 'binutils', 'python3', 'libpython3',
                'libc6', 'libgcc', 'libstdc++', 'libelf', 'libdw', 'libbpf',
                'libssl', 'zlib', 'libzstd', 'liblzma', 'libncurses', 'libtinfo',
                'libclang', 'libllvm', 'libffi', 'libxml2', 'libedit', 'libcrypt',
                'libmpfr', 'libgmp', 'libmpc', 'libbinutils', 'libctf', 'libsframe')
    installed = output(['dpkg-query', '-W', '-f=${binary:Package}=${Version}\n'])
    return sorted(line for line in installed.splitlines()
                  if (name := line.split('=', 1)[0].split(':', 1)[0]) in tools
                  or name.startswith(prefixes))


def normalize_source_mtimes(kernel, epoch):
    for directory, folders, files in os.walk(kernel):
        folders[:] = [name for name in folders if name != '.git']
        for name in files:
            if name != '.git':
                os.utime(Path(directory) / name, (epoch, epoch), follow_symlinks=False)


def prepare_kernel_objects(make, objects, candidate, recipe, cache_hit):
    if cache_hit:
        validate_kernel(objects, recipe)
        print('Exact kernel cache validated; skipping modules_prepare and vmlinux/modules', flush=True)
        return
    objects.mkdir()
    shutil.copyfile(candidate / '.config', objects / '.config')
    run(make + ['modules_prepare'])
    run(make + ['vmlinux', 'modules'])
    record_kernel(objects, recipe)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=PROFILES)
    parser.add_argument('--work', type=Path, default=Path('work'))
    parser.add_argument('--dist', type=Path, default=Path('dist'))
    parser.add_argument('--jobs', type=int, default=os.cpu_count())
    parser.add_argument('--configure-only', action='store_true',
                        help='Apply upstream board preparation and validate olddefconfig only')
    parser.add_argument('--stage', choices=('all', 'configure', 'kernel', 'modules'), default='all')
    parser.add_argument('--cache-hit', action='store_true', help='Require and validate an exact restored kernel cache')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    work, dist = args.work.resolve(), args.dist.resolve()
    inputs = json.loads((work / 'inputs.json').read_text())
    kernel = work / f'kernel-{args.profile}'
    objects = work / f'objects-{args.profile}'
    candidate = work / f'config-{args.profile}'
    recipe_path = work / f'recipe-{args.profile}.json'
    stage = 'configure' if args.configure_only else args.stage
    # Fixed Kbuild metadata makes both the kernel and ccache inputs reproducible.
    epoch = int(output(['git', '-C', work / 'linux', 'show', '-s', '--format=%ct',
                        inputs['kernel_commit']]))
    timestamp = output(['git', '-C', work / 'linux', 'show', '-s', '--format=%cD',
                        inputs['kernel_commit']])
    os.environ.update(KBUILD_BUILD_TIMESTAMP=timestamp, KBUILD_BUILD_USER='e5',
                      KBUILD_BUILD_HOST='camera-builder', KBUILD_BUILD_VERSION='1',
                      CCACHE_BASEDIR=str(root), CCACHE_NOHASHDIR='true',
                      CCACHE_COMPILERCHECK='content')
    # The running configs were generated without Rust compiler feature probes.
    make = ['make', '--no-print-directory', '-C', kernel, 'ARCH=arm64', 'LLVM=-18',
            'CC=ccache clang-18', 'RUSTC=false', 'LOCALVERSION=', f'-j{args.jobs}']
    if stage in ('all', 'configure'):
        toolchain = {}
        for tool in ('clang-18', 'ld.lld-18', 'llvm-ar-18', 'llvm-nm-18',
                     'llvm-objcopy-18', 'llvm-readelf-18', 'pahole', 'cc', 'ld',
                     'make', 'ccache', 'python3', 'bison', 'flex'):
            toolchain[tool] = output([tool, '--version'])
        # Package revisions include the host libraries used by Kbuild and pahole.
        toolchain['packages'] = build_package_versions()
        toolchain['machine'] = platform.machine()
        if 'clang version 18.' not in toolchain['clang-18']:
            raise ValueError('LLVM18 is required')
        run(['git', '-C', work / 'linux', 'worktree', 'add', '--detach', kernel,
             inputs['kernel_commit']])
        run([sys.executable, work / 'board/devices' / args.profile / 'prepare-kernel.py', kernel])
        # Checkout/prepare mtimes must precede cached dependency outputs. This
        # includes Kconfig and Makefiles, preventing an external build from
        # regenerating auto.conf merely because its source tree was recreated.
        normalize_source_mtimes(kernel, epoch)
        candidate.mkdir()
        shutil.copyfile(root / 'configs' / f'{args.profile}.config', candidate / '.config')
        run(make + [f'O={candidate}', 'olddefconfig'])
        config = candidate / '.config'
        verify_running_config(root / 'configs' / f'{args.profile}.config', config)
        release = output(make + [f'O={candidate}', '-s', 'kernelrelease'])
        if not re.fullmatch(r'[A-Za-z0-9_.+-]+', release):
            raise ValueError(f'Invalid kernel release: {release}')
        recipe = dict(profile=args.profile, kernel_commit=inputs['kernel_commit'],
                      board_commit=inputs['board_commit'], kernel_release=release,
                      input_config_sha256=sha256(root / 'configs' / f'{args.profile}.config'),
                      effective_config_sha256=sha256(config), config_sha256=config_sha256(config),
                      toolchain=toolchain, rustc='false', timestamp=timestamp,
                      kernel_path=str(kernel), objects_path=str(objects),
                      scripts={name: sha256(root / 'scripts' / name) for name in
                               ('build.py', 'kernel_cache.py', 'prepare.py', 'common.py', 'install-deps.sh')})
        write_json(recipe_path, recipe)
        ccache_prefix = f'ccache-v1-{args.profile}-{digest(toolchain)}-'
        if 'GITHUB_OUTPUT' in os.environ:
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                stream.write(f'kernel_key={cache_key(recipe)}\n')
                stream.write(f'ccache_prefix={ccache_prefix}\n')
        print(f'Kernel cache key: {cache_key(recipe)}', flush=True)
        if stage == 'configure':
            return
    else:
        recipe = json.loads(recipe_path.read_text())
    if recipe['profile'] != args.profile or any(recipe[key] != inputs[key]
                                               for key in ('board_commit', 'kernel_commit')):
        raise ValueError('Build recipe differs from profile/source snapshot')
    make += [f'O={objects}']
    config = objects / '.config'
    if stage in ('all', 'kernel'):
        prepare_kernel_objects(make, objects, candidate, recipe, args.cache_hit)
        if stage == 'kernel':
            return
    else:
        validate_kernel(objects, recipe)
    release = recipe['kernel_release']
    entry = dict(inputs, profile=args.profile, kernel_release=release,
                 config_sha256=config_sha256(config),
                 asset=f'sprd-camera-{args.profile}-{release}-arm64.tar.gz')
    metadata = dict(entry, recipe=recipe, kernel_cache_key=cache_key(recipe))
    write_json(objects / 'build-inputs.json', metadata)
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
    if sha256(config) != recipe['effective_config_sha256']:
        raise ValueError('External module build changed the effective config')
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
