"""Prepare real JIT payload variants and inspect runtime loader evidence."""
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess


def manifest(payload, name):
    return dict(path=name, size=payload.stat().st_size,
                sha256=hashlib.sha256(payload.read_bytes()).hexdigest())


def prepare(workspace, sdk, closure):
    library = 'libclrjit.dylib' if platform.system() == 'Darwin' else 'libclrjit.so'
    original = sdk / 'shared/Microsoft.NETCore.App/10.0.0' / library
    directory = workspace / 'loader'
    directory.mkdir()
    first, second = directory / 'jit-v1', directory / 'jit-v2'
    shutil.copyfile(original, first)
    shutil.copyfile(original, second)
    if platform.system() == 'Darwin':
        # Change only the Mach-O UUID, then ad-hoc sign using the pinned Nix
        # signing tool. Executable instructions and JIT interface stay intact.
        data = bytearray(second.read_bytes())
        if data[:4] != b'\xcf\xfa\xed\xfe':
            raise ValueError('expected little-endian 64-bit Mach-O JIT')
        count = struct.unpack_from('<I', data, 16)[0]
        offset = 32
        for _ in range(count):
            command, size = struct.unpack_from('<II', data, offset)
            if command == 0x1b:  # LC_UUID
                data[offset + 8] ^= 1
                break
            offset += size
        else:
            raise ValueError('JIT Mach-O UUID not found')
        second.write_bytes(data)
        signer = next(Path(root) / 'bin/codesign' for root in closure['storePaths']
                      if Path(root).name.endswith('-sigtool-0.1.3'))
        subprocess.run([str(signer), '-f', '-s', '-', str(second)], check=True,
                       capture_output=True, text=True)
    else:
        # An ELF trailing marker changes bytes without changing load segments.
        with second.open('ab') as stream:
            stream.write(b'\nadapter-jit-payload-v2\n')
    first_info, second_info = manifest(first, library), manifest(second, library)
    if first_info['sha256'] == second_info['sha256']:
        raise ValueError('JIT variants must differ')
    return dict(original=str(original), library=library, first=first_info, second=second_info,
                mutation='Mach-O UUID plus ad-hoc signature' if platform.system() == 'Darwin' else 'ELF trailing marker')


def select(workspace, version, library):
    source = workspace / 'loader' / ('jit-' + version)
    (workspace / 'loader/manifest.json').write_text(json.dumps(manifest(source, library), indent=2) + '\n')


def evidence(workspace, output, case, expected_hash):
    result = {}
    for project in ('shared', 'app'):
        directory = workspace / f'bazel-bin/{project}.diagnostics'
        runtime = json.loads((directory / 'loader-runtime.json').read_text())
        trace = '\n'.join(path.read_text() for path in sorted(directory.glob('loader.log*')))
        loaded = sorted(set(re.findall(r'^dyld\[\d+\]:.*? (/[^\n]+)$', trace, re.MULTILINE)
                            if platform.system() == 'Darwin' else
                            re.findall(r'calling init:\s*(/[^\n]+)', trace)))
        log = output / f'{case}-{project}-loader.log'
        log.write_text(trace)
        if runtime['sha256'] != expected_hash or runtime['jitPath'] not in loaded:
            raise RuntimeError('staged JIT loading not observed: ' + project)
        if runtime['originalJitPath'] in loaded:
            raise RuntimeError('original JIT fallback observed: ' + project)
        result[project] = dict(runtime, loaded=loaded, log=str(log))
    return result
