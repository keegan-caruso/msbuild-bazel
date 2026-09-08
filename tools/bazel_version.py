"""Validate an exact selected Bazel release, allowing Nixpkgs' release suffix."""


def validate_version(output, expected):
    label = output.strip().splitlines()[-1] if output.strip() else ''
    if label not in ('bazel ' + expected, 'bazel ' + expected + '- (@non-git)'):
        raise ValueError('expected pinned Bazel ' + expected + ': ' + output)
    return label
