"""Compiler-process policy for the pinned runtime qualification adapter.

Roslyn normally keys its server pipe by compiler location. Package compiler
locations change with each isolated action's input identity. Use the declared
compiler archive identity instead, scoped to this SDK. The worker's private TMP
namespace prevents cross-worker reuse; Bazel still owns all action caching.
"""
import hashlib
import json


def compiler_properties(locked, manifest, sdk_version):
    result = {'UseSharedCompilation': 'true'}
    compiler = locked.get('microsoft.net.compilers.toolset')
    if compiler is not None:
        key = compiler[0]
        archive = manifest[key]['sha256']
        if len(archive) != 64 or any(c not in '0123456789abcdef' for c in archive):
            raise ValueError('Compiler archive must have a locked SHA-256')
        identity = ['runtime-compiler-v1', sdk_version, key.lower(), archive]
        result['SharedCompilationId'] = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return result
