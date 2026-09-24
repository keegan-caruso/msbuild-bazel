"""Select pinned bootstrap downloads without silently falling back across architectures."""


def select(pins, machine, system="Linux"):
    if (system, machine) not in [('Linux', 'x86_64'), ('Linux', 'aarch64'), ('Linux', 'arm64'), ('Darwin', 'arm64')]:
        raise ValueError(f'Unsupported bootstrap platform: {system}/{machine}')
    selected = {}
    for name in ('dotnet', 'bazelisk'):
        pin = pins[name]
        download = pin if machine == 'x86_64' else pin['platforms']['osx-arm64' if system == 'Darwin' else 'linux-arm64']
        selected[name] = {'version': pin['version'], 'url': download['url'],
                          'sha256': download['sha256']}
    return selected
