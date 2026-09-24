"""Analysis controls for per-consumer package resolution and inherited frameworks.

Takes an existing explicit acceptance workspace (created by acceptance.py).
No package actions execute: deliberately empty archives isolate graph contracts.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

folder = Path(sys.argv[1]).resolve()
workspace = folder/'src'
fixture = workspace/'Locks'
fixture.mkdir(exist_ok=True)
(fixture/'empty.nupkg').write_bytes(b'')
(fixture/'Project.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk" />')
header = '''load("@rules_msbuild//msbuild:defs.bzl", "msbuild_library", "msbuild_nuget_package", "msbuild_nuget_dependencies", "msbuild_package_lock")
msbuild_nuget_package(name="v1", package_id="Example", version="1.0.0", archive="empty.nupkg", archive_sha256="0"*64, content_hash="unused")
msbuild_nuget_package(name="v2", package_id="Example", version="2.0.0", archive="empty.nupkg", archive_sha256="0"*64, content_hash="unused")
msbuild_nuget_dependencies(name="resolved", package=":v2")
msbuild_package_lock(name="selected", packages=[":resolved"])
msbuild_library(name="producer", project="Project.csproj", target_framework="net10.0", deps=[":v1"], framework_refs=["Microsoft.AspNetCore.App"])
'''
cmd = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base='+str(folder/'lock-base'), '--ignore_all_rc_files']
cases = [
    ('resolved-version', 'package_lock=":selected", deps=[":producer", ":resolved"]', None),
    ('unresolved-conflict', 'deps=[":producer", ":resolved"]', 'Conflicting inherited package'),
    ('direct-mismatch', 'package_lock=":selected", deps=[":v1"]', 'Direct package closure disagrees'),
]
try:
    for name, attrs, error in cases:
        (fixture/'BUILD.bazel').write_text(header+'msbuild_library(name="consumer", project="Project.csproj", target_framework="net10.0", '+attrs+')\n')
        p = subprocess.run(cmd+['build', '//Locks:consumer', '--nobuild', '--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE']], cwd=workspace, capture_output=True, text=True)
        output = p.stdout+p.stderr
        (folder/(name+'.log')).write_text(output)
        assert (p.returncode == 0) if error is None else (p.returncode != 0 and error in output), output
        print(name, 'passed', flush=True)
finally:
    subprocess.run(cmd+['shutdown'], cwd=workspace, check=True)
