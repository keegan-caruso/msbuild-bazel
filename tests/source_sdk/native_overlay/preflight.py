"""Capture and probe the source SDK native root in its sealed build boundary."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

from install import digest

sys.path.insert(0, '/rules/tests/source_sdk')
from source_action_prepare import normalize
from native_environment import build_prefix


def main():
    proof = Path('/proof')
    root = Path('/sealed')
    source = Path('/probe')
    root.mkdir()
    source.mkdir()
    native_archive = Path('/native.tar')
    names = ['usr', 'bin', 'lib', 'sbin', 'etc/alternatives', 'etc/ld.so.conf',
             'etc/ld.so.conf.d', 'etc/ld.so.cache', 'etc/os-release', 'etc/ssl/certs',
             'etc/ssl/openssl.cnf', 'etc/passwd', 'etc/group', 'etc/nsswitch.conf']
    with tarfile.open(native_archive, 'w') as archive:
        for name in names:
            archive.add('/' + name, arcname=name, filter=normalize)
        for name in ['source', 'proc', 'dev', 'tmp']:
            entry = tarfile.TarInfo(name)
            entry.type, entry.mode = tarfile.DIRTYPE, 0o755
            archive.addfile(normalize(entry))
    subprocess.run(['tar', '--same-permissions', '-xf', str(native_archive), '-C', str(root)], check=True)
    script = build_prefix() + '''
for tool in file cpio python clang-18 clang++-18 lld-18 llvm-config-18 lldb-18 msgfmt localedef pigz time; do command -v "$tool"; done
file /bin/sh
file /usr/bin/file | grep 'ELF 64-bit'
file --version
cpio --version
python --version
lldb-18 --version
pkg-config --modversion libbrotlidec
for tool in /usr/bin/file /usr/bin/clang-18 /usr/bin/lldb-18; do
 ldd "$tool" > /source/ldd-$(basename "$tool").txt
 ! grep 'not found' /source/ldd-$(basename "$tool").txt
done
printf '#include <brotli/decode.h>\nint main(void){return BrotliDecoderVersion() == 0;}\n' > /source/probe.c
clang-18 /source/probe.c -lbrotlidec -o /source/probe
/source/probe
printf 'PASS: sealed root tools, LLVM18, libbrotli compile/link/execute\n'
'''
    (source/'probe.sh').write_text(script)
    command = ['bwrap', '--die-with-parent', '--unshare-all', '--new-session', '--cap-drop', 'ALL',
               '--ro-bind', str(root), '/', '--bind', str(source), '/source', '--proc', '/proc',
               '--dev', '/dev', '--tmpfs', '/tmp', '--chdir', '/source', '--clearenv',
               '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'HOME', '/tmp',
               '--setenv', 'LANG', 'C.UTF-8', '--', '/bin/bash', 'probe.sh']
    with (proof/'sealed.log').open('w') as output:
        subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, check=True, timeout=120)
    shutil.copytree('/opt/source-sdk-prerequisites', proof/'packages')
    shutil.copytree(source, proof/'probe')
    report = dict(result='PASS', nativeArchiveSha256=digest(native_archive),
                  nativeArchiveBytes=native_archive.stat().st_size,
                  preparationHelperSha256=digest(Path('/rules/tests/source_sdk/source_action_prepare.py')),
                  boundary=command)
    (proof/'sealed.json').write_text(json.dumps(report, indent=2))
    print((proof/'sealed.log').read_text())


if __name__ == '__main__':
    main()
