#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  ca-certificates git python3 make clang-18 lld-18 llvm-18 \
  gcc g++ binutils bison flex bc libssl-dev libelf-dev dwarves \
  libncurses-dev rsync cpio kmod zstd xz-utils ccache
