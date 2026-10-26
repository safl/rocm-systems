#!/usr/bin/env python3
"""
Package the rocjitsu vfio-user server as rocjitsu-host, for the hosts
=====================================================================

Built with clang, since libvfio-user's headers use C11 _Static_assert, which
g++ rejects in the C++ that includes them; rocjitsu links libvfio-user and
json-c statically, so everything else the binaries link must come from the
archive, and becomes the package's Depends.

The deb is <version>+xnvme<n> for a release, or <version>+xnvme0~g<commit>
for a build of the branch, with 'xnvme_ci.n' as <n>. Next to rocjitsu's
device configs it ships 'xnvme_ci.gpu_config', which is
'xnvme_ci.gpu_config_base' with a VRAM window of 'xnvme_ci.vram_aperture_mib'.

Retargetable: true
------------------
"""
import errno
import logging as log
import shlex

RJ = "emulation/rocjitsu"
HERE = f"{RJ}/packaging/xnvme-ci"
DERIVE_CONFIG = (
    "python3 -I -c 'import json,sys; c=json.load(open(sys.argv[1])); "
    "c[\"vm\"][\"gpu\"][\"pci\"][\"vram_aperture_bytes\"]=int(sys.argv[3]); "
    "json.dump(c,open(sys.argv[2],\"w\"),indent=2)'"
)


def main(args, cijoe):
    """Build the rocjitsu-host deb into 'xnvme_ci.out'"""

    src = cijoe.getconf("xnvme_ci.src")
    out = cijoe.getconf("xnvme_ci.out")
    n = int(cijoe.getconf("xnvme_ci.n"))
    config_base = cijoe.getconf("xnvme_ci.gpu_config_base")
    config = cijoe.getconf("xnvme_ci.gpu_config")
    aperture_mib = int(cijoe.getconf("xnvme_ci.vram_aperture_mib"))

    err, state = cijoe.run(
        f"sed -n 's/^project(rocm_jit_suite VERSION \\([0-9.]*\\)).*/\\1/p' {RJ}/CMakeLists.txt && "
        "git rev-parse --short HEAD",
        cwd=src,
    )
    if err or len(state.output().split()) < 2:
        log.error(f"could not read rocjitsu's version in {src}")
        return errno.EINVAL
    base, sha = state.output().split()[-2:]
    version = f"{base}+xnvme{n}" if n else f"{base}+xnvme0~g{sha}"
    log.info(f"packaging rocjitsu-host {version}")

    err, _ = cijoe.run(
        "build=$(mktemp -d) && echo $build > /tmp/rj-host-build && "
        f"CC=clang CXX=clang++ cmake -S {RJ} -B $build -G Ninja -DCMAKE_BUILD_TYPE=Release "
        "-DROCJITSU_ENABLE_VFIO=ON && cmake --build $build --target rocjitsu_bin rj_ip_discovery",
        cwd=src,
    )
    if err:
        return err

    stage = "$build/stage"
    err, _ = cijoe.run(
        "build=$(cat /tmp/rj-host-build) && "
        f"install -D -m 0755 $build/tools/rocjitsu/rocjitsu {stage}/opt/rocjitsu/bin/rocjitsu && "
        "install -D -m 0755 $build/tools/rj-ip-discovery/rj-ip-discovery "
        f"{stage}/opt/rocjitsu/bin/rj-ip-discovery && "
        f"install -D -m 0755 {HERE}/rocjitsu-vram {stage}/opt/rocjitsu/bin/rocjitsu-vram && "
        f"mkdir -p {stage}/opt/rocjitsu/share && cp -r {RJ}/configs {stage}/opt/rocjitsu/share/configs && "
        f"{DERIVE_CONFIG} {stage}/opt/rocjitsu/share/configs/{config_base} "
        f"{stage}/opt/rocjitsu/share/configs/{config} {aperture_mib << 20} && "
        f"install -D -m 0644 {RJ}/LICENSE.md {stage}/usr/share/doc/rocjitsu-host/copyright",
        cwd=src,
    )
    if err:
        return err

    # Everything the binaries need must come from the archive
    bins = f"{stage}/opt/rocjitsu/bin/rocjitsu {stage}/opt/rocjitsu/bin/rj-ip-discovery"
    err, _ = cijoe.run(
        f"build=$(cat /tmp/rj-host-build) && ! ldd {bins} | grep -E \"=> $build/|not found\""
    )
    if err:
        log.error("a binary links something outside the base system")
        return errno.ENOENT
    err, state = cijoe.run(
        f"build=$(cat /tmp/rj-host-build) && ldd {bins} | awk '/=> \\// {{print $3}}' | sort -u | "
        "xargs -r realpath | xargs -r dpkg -S | cut -d: -f1 | sort -u | paste -sd, | sed 's/,/, /g'"
    )
    deps = state.output().strip().splitlines()[-1] if not err and state.output().strip() else ""
    if not deps:
        log.error("found no archive packages for the binaries' libraries")
        return errno.ENOENT
    err, state = cijoe.run("dpkg --print-architecture")
    arch = state.output().strip().splitlines()[-1]

    control = f"""Package: rocjitsu-host
Version: {version}
Architecture: {arch}
Maintainer: Simon A. F. Lund <os@safl.dk>
Depends: {deps}
Section: misc
Priority: optional
Homepage: https://github.com/safl/rocm-systems/tree/xnvme-ci/artifacts/emulation/rocjitsu
Description: rocjitsu emulated AMD GPU, served over vfio-user
 The rocjitsu vfio-user server from {sha}, built with
 ROCJITSU_ENABLE_VFIO, under /opt/rocjitsu, with its device configs,
 rj-ip-discovery, and rocjitsu-vram, which names the memfd backing a running
 server's VRAM BAR so another vfio-user server can DMA into it. The guest
 side is rocjitsu-guest-firmware of the same version.
"""
    return cijoe.run(
        f"build=$(cat /tmp/rj-host-build) && mkdir -p {stage}/DEBIAN {out} && "
        f"printf '%s' {shlex.quote(control)} > {stage}/DEBIAN/control && "
        f"dpkg-deb --root-owner-group -Zxz --build {stage} {out} && rm -rf $build && "
        f"ls {out}/rocjitsu-host_*.deb"
    )[0]
