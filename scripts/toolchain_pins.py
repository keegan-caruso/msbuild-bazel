"""Select pinned Linux downloads without silently falling back across architectures."""


def select(pins, machine):
    if machine not in ('x86_64', 'aarch64', 'arm64'):
        raise ValueError(f'Unsupported Linux architecture: {machine}')
    selected = {}
    for name in ('dotnet', 'bazel'):
        pin = pins[name]
        download = pin if machine == 'x86_64' else pin['platforms']['linux-arm64']
        selected[name] = {'version': pin['version'], 'url': download['url'],
                          'sha256': download['sha256']}
    return selected
