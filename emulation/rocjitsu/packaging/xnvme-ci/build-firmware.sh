#!/bin/bash
# Package the guest's firmware fixtures and amdgpu options as
# rocjitsu-guest-firmware.
#
#   build-firmware.sh <rocjitsu-host .deb> <output dir>
#
# ip_discovery.bin comes from that rocjitsu-host's rj-ip-discovery, so it
# describes the GPU that server presents, and the package takes its version.
#
# Copyright (c) Simon A. F. Lund <os@safl.dk>
# SPDX-License-Identifier: MIT
set -euo pipefail
host_deb=$(realpath "$1")
out=$(realpath "$2")
here=$(cd "$(dirname "$0")" && pwd)
rj=$(cd "$here/../.." && pwd)

export DEBIAN_FRONTEND=noninteractive
apt-get -qy update >/dev/null
apt-get -qy install --no-install-recommends python3 >/dev/null

work=$(mktemp -d)
version=$(dpkg-deb -f "$host_deb" Version)
dpkg-deb -x "$host_deb" "$work/host"
stage=$work/stage
fw=$stage/lib/firmware/updates/amdgpu
mkdir -p "$(dirname "$fw")"

python3 -I "$rj/tools/vfio_guest_firmware.py" --output "$fw"
"$work/host/opt/rocjitsu/bin/rj-ip-discovery" gfx1250 "$fw/ip_discovery.bin"

# The fixture's MEC reports ucode_version 1. KFD then wants PCIe atomics from
# the root port, which QEMU never offers a vfio-user device; 2090 is the gfx12
# MEC release KFD accepts without them. ucode_version is outside the CRC.
python3 -I - "$fw/gc_12_1_0_mec.bin" <<'PY'
import struct, sys
with open(sys.argv[1], "r+b") as f:
    f.seek(16)
    f.write(struct.pack("<I", 2090))
PY

install -D -m 0644 "$here/amdgpu-rocjitsu.conf" "$stage/etc/modprobe.d/amdgpu-rocjitsu.conf"
install -D -m 0644 "$rj/LICENSE.md" "$stage/usr/share/doc/rocjitsu-guest-firmware/copyright"

mkdir -p "$stage/DEBIAN"
echo /etc/modprobe.d/amdgpu-rocjitsu.conf >"$stage/DEBIAN/conffiles"
cat >"$stage/DEBIAN/control" <<CONTROL
Package: rocjitsu-guest-firmware
Version: $version
Architecture: all
Maintainer: Simon A. F. Lund <os@safl.dk>
Section: kernel
Priority: optional
Description: firmware and amdgpu options for a guest with a rocjitsu GPU
 Firmware-format fixtures from rocjitsu (headers and sentinel payloads, not
 AMD firmware) and the ip_discovery.bin of rocjitsu-host $version, under
 /lib/firmware/updates/amdgpu, plus the amdgpu emulation options.
 .
 Install it only in a guest whose GPU is rocjitsu: the options it sets break
 a real AMD GPU. udevd reads modprobe.d when it starts, so load amdgpu by hand
 after installing and before the GPU appears, or install it before udevd runs.
CONTROL
mkdir -p "$out"
dpkg-deb --root-owner-group -Zxz --build "$stage" "$out" >/dev/null
rm -rf "$work"
ls "$out"/rocjitsu-guest-firmware_*.deb
