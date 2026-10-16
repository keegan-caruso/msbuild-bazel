"""Deterministic version inputs for the pinned runtime native qualification.

This bounded bootstrap uses the authored product version and source commit. It
does not reproduce official servicing/build-number or signing infrastructure.
"""
import re
import xml.etree.ElementTree as ET


def version_inputs(source, commit):
    document = ET.fromstring((source / 'eng/Versions.props').read_text())
    properties = {item.tag: item.text for group in document for item in group}
    version = properties['ProductVersion']
    assert re.fullmatch(r'\d+\.\d+\.\d+', version)
    major, minor, patch = map(int, version.split('.'))
    assert (major, minor, patch) == tuple(int(properties[name]) for name in ['MajorVersion', 'MinorVersion', 'PatchVersion'])
    assert re.fullmatch(r'[0-9a-f]{40}', commit)
    header = (source / 'eng/native/version/_version.h').read_text()
    header = header.replace('00,00,00,00000', f'{major},{minor},{patch},0').replace('"0.0.0"', '"' + version + '"')
    values = dict(RuntimeAssemblyMajorVersion=major, RuntimeAssemblyMinorVersion=minor,
        RuntimeFileMajorVersion=major, RuntimeFileMinorVersion=minor, RuntimeFileBuildVersion=patch,
        RuntimeFileRevisionVersion=0, RuntimeProductMajorVersion=major, RuntimeProductMinorVersion=minor,
        RuntimeProductPatchVersion=patch, RuntimeProductVersion=version)
    runtime = (source / 'eng/native/version/runtime_version.h').read_text()
    for name, value in values.items():
        runtime, count = re.subn(r'(?m)^(#define ' + name + r' )[^\n]+$', lambda match: match[1] + str(value), runtime)
        assert count == 1, name
    implementation = (source / 'eng/native/version/_version.c').read_text()
    assert implementation.count('@(#)No version information produced') == 1
    implementation = implementation.replace('@(#)No version information produced', '@(#)Version ' + version + ' @Commit: ' + commit)
    return {'_version.h': header, 'runtime_version.h': runtime, '_version.c': implementation}
