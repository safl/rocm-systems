#!/bin/bash
# Package the rocjitsu vfio-user server as rocjitsu-host, for the hosts that
# serve the GPU.
#
#   build-host.sh <output dir> <deb version>
#
# Runs as root in a container of the release the host runs. clang, since
# libvfio-user's headers use C11 _Static_assert, which g++ rejects in the C++
# that includes them; rocjitsu links libvfio-user and json-c statically.
#
# Copyright (c) Simon A. F. Lund <os@safl.dk>
# SPDX-License-Identifier: MIT
set -euo pipefail
out=$(realpath "$1")
version=$2
here=$(cd "$(dirname "$0")" && pwd)
rj=$(cd "$here/../.." && pwd)

export DEBIAN_FRONTEND=noninteractive
apt-get -qy update >/dev/null
apt-get -qy install --no-install-recommends build-essential clang cmake ninja-build git \
	ca-certificates python3 file >/dev/null

build=$(mktemp -d)
CC=clang CXX=clang++ cmake -S "$rj" -B "$build" -G Ninja -DCMAKE_BUILD_TYPE=Release \
	-DROCJITSU_ENABLE_VFIO=ON
cmake --build "$build" --target rocjitsu_bin rj_ip_discovery

stage=$build/stage
install -D -m 0755 "$build/tools/rocjitsu/rocjitsu" "$stage/opt/rocjitsu/bin/rocjitsu"
install -D -m 0755 "$build/tools/rj-ip-discovery/rj-ip-discovery" \
	"$stage/opt/rocjitsu/bin/rj-ip-discovery"
install -D -m 0755 "$here/rocjitsu-vram" "$stage/opt/rocjitsu/bin/rocjitsu-vram"
mkdir -p "$stage/opt/rocjitsu/share"
cp -r "$rj/configs" "$stage/opt/rocjitsu/share/configs"
install -D -m 0644 "$rj/LICENSE.md" "$stage/usr/share/doc/rocjitsu-host/copyright"

# Everything the binaries need must come from the archive.
bins="$stage/opt/rocjitsu/bin/rocjitsu $stage/opt/rocjitsu/bin/rj-ip-discovery"
if ldd $bins | grep -E "=> $build/|not found"; then
	echo "build-host.sh: a binary links something outside the base system" >&2
	exit 1
fi
deps=$(ldd $bins | awk '/=> \// {print $3}' | sort -u | xargs -r realpath |
	xargs -r dpkg -S | cut -d: -f1 | sort -u | paste -sd, | sed 's/,/, /g')
[ -n "$deps" ]

mkdir -p "$stage/DEBIAN"
cat >"$stage/DEBIAN/control" <<CONTROL
Package: rocjitsu-host
Version: $version
Architecture: $(dpkg --print-architecture)
Maintainer: Simon A. F. Lund <os@safl.dk>
Depends: $deps
Section: misc
Priority: optional
Homepage: https://github.com/safl/rocm-systems/tree/xnvme-ci/artifacts/emulation/rocjitsu
Description: rocjitsu emulated AMD GPU, served over vfio-user
 The rocjitsu vfio-user server from $(git -C "$rj" rev-parse --short HEAD), built with
 ROCJITSU_ENABLE_VFIO, under /opt/rocjitsu, with its device configs,
 rj-ip-discovery, and rocjitsu-vram, which names the memfd backing a running
 server's VRAM BAR so another vfio-user server can DMA into it. The guest
 side is rocjitsu-guest-firmware of the same version.
CONTROL
mkdir -p "$out"
dpkg-deb --root-owner-group -Zxz --build "$stage" "$out" >/dev/null
rm -rf "$build"
ls "$out"/rocjitsu-host_*.deb
