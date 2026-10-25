#!/bin/bash
# Install rocjitsu-host and rocjitsu-guest-firmware into a fresh container and
# check what a guest and its host rely on: the server runs, the firmware is
# where amdgpu looks, the MEC carries the stamped release, ip_discovery.bin
# is the host's, and the options are in place.
#
#   test-packages.sh <dir with both .debs>
#
# Copyright (c) Simon A. F. Lund <os@safl.dk>
# SPDX-License-Identifier: MIT
set -euo pipefail
debs=$(realpath "$1")

export DEBIAN_FRONTEND=noninteractive
apt-get -qy update >/dev/null
apt-get -qy install --no-install-recommends python3 "$debs"/rocjitsu-host_*.deb \
	"$debs"/rocjitsu-guest-firmware_*.deb >/dev/null

/opt/rocjitsu/bin/rocjitsu --version
fw=/lib/firmware/updates/amdgpu
for f in gc_12_1_0_mec.bin ip_discovery.bin; do
	test -s "$fw/$f"
done
mec=$(python3 -I -c 'import struct,sys; d=open(sys.argv[1],"rb").read(); print(struct.unpack_from("<I",d,16)[0])' "$fw/gc_12_1_0_mec.bin")
[ "$mec" = 2090 ] || { echo "test-packages.sh: MEC ucode_version $mec, not 2090" >&2; exit 1; }
tmp=$(mktemp)
/opt/rocjitsu/bin/rj-ip-discovery gfx1250 "$tmp"
cmp "$tmp" "$fw/ip_discovery.bin"
grep -q '^options amdgpu .*discovery=2' /etc/modprobe.d/amdgpu-rocjitsu.conf
# vramlimit (MiB) must equal the BAR the server presents, or pins move buffers
aperture=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["vm"]["gpu"]["pci"]["vram_aperture_bytes"] >> 20)' \
	/opt/rocjitsu/share/configs/gfx1250_mi455x.json)
grep -q "^options amdgpu .*vramlimit=$aperture\b" /etc/modprobe.d/amdgpu-rocjitsu.conf || {
	echo "test-packages.sh: amdgpu vramlimit is not the ${aperture} MiB BAR" >&2
	exit 1
}
echo "test-packages.sh: ok"
