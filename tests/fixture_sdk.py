"""Shared declarations for ordinary SDK-backed qualification workspaces."""
import json
import platform


def sdk_declarations(name="dotnet", version="10.0.400", extra_toolchains=()):
    """Acquire the fixture platform's verified SDK and register its toolchains."""
    system = {"Darwin": "osx", "Linux": "linux"}.get(platform.system())
    cpu = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "AMD64": "x64"}.get(platform.machine())
    if not system or not cpu:
        raise ValueError("Unsupported fixture SDK platform")
    return '\n'.join([
        'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")',
        'dotnet.sdk(name='+json.dumps(name)+',version='+json.dumps(version)+',platforms='+json.dumps([system+'-'+cpu])+')',
        'use_repo(dotnet,'+json.dumps(name)+')',
        'register_toolchains('+','.join(json.dumps(x) for x in [*extra_toolchains, '@'+name+'//:all'])+')',
        '',
    ])
