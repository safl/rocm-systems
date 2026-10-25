#!/usr/bin/env python3
"""
Install rocjitsu-host and rocjitsu-guest-firmware and check what each relies on
===============================================================================

Installs both debs from 'xnvme_ci.out' and checks that the server runs; that
the firmware is where amdgpu looks, with the MEC stamped 2090; that
ip_discovery.bin is the one this rocjitsu-host's rj-ip-discovery writes; and
that the amdgpu options are in place, with vramlimit equal to the BAR the
server's 'xnvme_ci.gpu_config' presents. A larger vramlimit lets amdgpu place
buffers outside the BAR, which a dma-buf pin then moves, evicting the
process's queues, which rocjitsu does not restore.

Retargetable: true
------------------
"""
import errno
import logging as log

FW = "/lib/firmware/updates/amdgpu"
CONF = "/etc/modprobe.d/amdgpu-rocjitsu.conf"


def main(args, cijoe):
    """Install and check both debs"""

    out = cijoe.getconf("xnvme_ci.out")
    gpu = cijoe.getconf("xnvme_ci.gpu")
    gpu_config = cijoe.getconf("xnvme_ci.gpu_config")

    err, _ = cijoe.run(
        "export DEBIAN_FRONTEND=noninteractive && apt-get -qy update && "
        f"apt-get -qy install --no-install-recommends python3 {out}/rocjitsu-host_*.deb "
        f"{out}/rocjitsu-guest-firmware_*.deb && /opt/rocjitsu/bin/rocjitsu --version"
    )
    if err:
        return err

    err, _ = cijoe.run(f"test -s {FW}/gc_12_1_0_mec.bin && test -s {FW}/ip_discovery.bin")
    if err:
        log.error(f"the firmware is not under {FW}")
        return err

    err, state = cijoe.run(
        "python3 -I -c 'import struct,sys; d=open(sys.argv[1],\"rb\").read(); "
        f"print(struct.unpack_from(\"<I\",d,16)[0])' {FW}/gc_12_1_0_mec.bin"
    )
    mec = state.output().strip().splitlines()[-1] if not err else ""
    if mec != "2090":
        log.error(f"MEC ucode_version {mec}, not 2090")
        return errno.EINVAL

    err, _ = cijoe.run(
        f"tmp=$(mktemp) && /opt/rocjitsu/bin/rj-ip-discovery {gpu} $tmp && cmp $tmp {FW}/ip_discovery.bin"
    )
    if err:
        log.error("ip_discovery.bin is not this rocjitsu-host's")
        return err

    err, _ = cijoe.run(f"grep '^options amdgpu .*discovery=2' {CONF}")
    if err:
        log.error(f"{CONF} lacks the amdgpu options")
        return err

    err, state = cijoe.run(
        "python3 -I -c 'import json,sys; "
        "print(json.load(open(sys.argv[1]))[\"vm\"][\"gpu\"][\"pci\"][\"vram_aperture_bytes\"] >> 20)' "
        f"/opt/rocjitsu/share/configs/{gpu_config}"
    )
    if err:
        return err
    aperture = state.output().strip().splitlines()[-1]
    err, _ = cijoe.run(f"grep '^options amdgpu .*vramlimit={aperture}\\b' {CONF}")
    if err:
        log.error(f"amdgpu vramlimit is not the {aperture} MiB BAR")
    return err
