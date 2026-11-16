"""Reviewed source adaptation for the pinned runtime, before input discovery."""
import hashlib

LINKER_DRIVER = 'src/tools/illink/src/linker/Linker/Driver.cs'
LINKER_SHA256 = 'f7e21005c7bea41beaad2a92c6e6b00f6d40d81adee00d746a2e0dd22655e0cf'


def compatible_source(relative, data):
    if relative != LINKER_DRIVER:
        return data
    # SDK 11's CA1830 rejects the temporary string. The repeated-character
    # overload preserves the existing positive-count guard and output bytes.
    if hashlib.sha256(data).hexdigest() != LINKER_SHA256:
        raise ValueError('Pinned runtime linker source changed; review its compatibility adaptation')
    before = b"argBuilder.Append(new string('\\\\', numBackslash));"
    after = b"argBuilder.Append('\\\\', numBackslash);"
    if data.count(before) != 1:
        raise ValueError('Pinned runtime linker append is missing or ambiguous')
    return data.replace(before, after)
