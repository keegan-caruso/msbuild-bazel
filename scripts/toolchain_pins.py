"""Select pinned bootstrap downloads without silently falling back across architectures."""


def select(pins, machine, system="Linux"):
    platforms = {('Linux', 'x86_64'): 'linux-x64', ('Linux', 'aarch64'): 'linux-arm64',
                 ('Linux', 'arm64'): 'linux-arm64', ('Darwin', 'arm64'): 'osx-arm64',
                 ('Windows', 'AMD64'): 'win-x64', ('Windows', 'x86_64'): 'win-x64'}
    platform = platforms.get((system, machine))
    if platform is None:
        raise ValueError(f'Unsupported bootstrap platform: {system}/{machine}')
    selected = {}
    for name in ('dotnet', 'bazelisk'):
        pin = pins[name]
        download = pin if platform == 'linux-x64' else pin['platforms'][platform]
        selected[name] = {'version': pin['version'], 'url': download['url'],
                          'sha256': download['sha256']}
    return selected
