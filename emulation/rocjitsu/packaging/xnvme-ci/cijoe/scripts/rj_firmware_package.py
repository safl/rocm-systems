#!/usr/bin/env python3
"""
Package the guest's firmware fixtures and amdgpu options
========================================================

Builds rocjitsu-guest-firmware from the rocjitsu-host deb in 'xnvme_ci.out':
its ip_discovery.bin comes from that deb's rj-ip-discovery, so it describes
the GPU that server presents, and the package takes its version.

The fixture's MEC reports ucode_version 1. KFD then wants PCIe atomics from
the root port, which QEMU never offers a vfio-user device; 2090 is the gfx12
MEC release KFD accepts without them. ucode_version is outside the CRC.

Retargetable: true
------------------
"""
import errno
import logging as log
import shlex

RJ = "emulation/rocjitsu"
HERE = f"{RJ}/packaging/xnvme-ci"
MEC_STAMP = (
    "python3 -I -c 'import struct,sys; f=open(sys.argv[1],\"r+b\"); "
    "f.seek(16); f.write(struct.pack(\"<I\", 2090))'"
)


def main(args, cijoe):
    """Build the rocjitsu-guest-firmware deb into 'xnvme_ci.out'"""

    src = cijoe.getconf("xnvme_ci.src")
    out = cijoe.getconf("xnvme_ci.out")
    gpu = cijoe.getconf("xnvme_ci.gpu")

    err, state = cijoe.run(f"dpkg-deb -f $(ls {out}/rocjitsu-host_*.deb) Version")
    if err:
        log.error(f"no rocjitsu-host deb in {out}")
        return errno.ENOENT
    version = state.output().strip().splitlines()[-1]

    fw = "$work/stage/lib/firmware/updates/amdgpu"
    err, _ = cijoe.run(
        "work=$(mktemp -d) && echo $work > /tmp/rj-fw-work && "
        f"dpkg-deb -x $(ls {out}/rocjitsu-host_*.deb) $work/host && mkdir -p $(dirname {fw}) && "
        f"python3 -I {RJ}/tools/vfio_guest_firmware.py --output {fw} && "
        f"$work/host/opt/rocjitsu/bin/rj-ip-discovery {gpu} {fw}/ip_discovery.bin && "
        f"{MEC_STAMP} {fw}/gc_12_1_0_mec.bin",
        cwd=src,
    )
    if err:
        return err

    control = f"""Package: rocjitsu-guest-firmware
Version: {version}
Architecture: all
Maintainer: Simon A. F. Lund <os@safl.dk>
Section: kernel
Priority: optional
Description: firmware and amdgpu options for a guest with a rocjitsu GPU
 Firmware-format fixtures from rocjitsu (headers and sentinel payloads, not
 AMD firmware) and the ip_discovery.bin of rocjitsu-host {version}, under
 /lib/firmware/updates/amdgpu, plus the amdgpu emulation options.
 .
 Install it only in a guest whose GPU is rocjitsu: the options it sets break
 a real AMD GPU. udevd reads modprobe.d when it starts, so load amdgpu by hand
 after installing and before the GPU appears, or install it before udevd runs.
"""
    stage = "$work/stage"
    return cijoe.run(
        "work=$(cat /tmp/rj-fw-work) && "
        f"install -D -m 0644 {HERE}/amdgpu-rocjitsu.conf {stage}/etc/modprobe.d/amdgpu-rocjitsu.conf && "
        f"install -D -m 0644 {RJ}/LICENSE.md {stage}/usr/share/doc/rocjitsu-guest-firmware/copyright && "
        f"mkdir -p {stage}/DEBIAN && echo /etc/modprobe.d/amdgpu-rocjitsu.conf > {stage}/DEBIAN/conffiles && "
        f"printf '%s' {shlex.quote(control)} > {stage}/DEBIAN/control && "
        f"dpkg-deb --root-owner-group -Zxz --build {stage} {out} && rm -rf $work && "
        f"ls {out}/rocjitsu-guest-firmware_*.deb",
        cwd=src,
    )[0]
