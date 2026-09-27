"""Prepare an isolated CommandLine rebuild with explicit upstream dependency bundles.

The source archive still contains the whole VMR. This proves dependency output
handoff before narrowing source inputs or scheduling all components with Bazel.
Requires Arcade and SBRP bundles made by component_outputs.py from the development
baseline. Invoke NativeBuild with this archive and the source action's native and
bootstrap archives; request result.tar and component.nupkg outputs.
"""
import argparse
import io
from pathlib import Path
import tarfile

from source_action_prepare import normalize

SCRIPT = '''set -euo pipefail
export DOTNET_PROCESSOR_COUNT=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_GENERATE_ASPNET_CERTIFICATE=false NuGetAudit=false
mkdir -p /tmp/component-inputs
mv prereqs/component-inputs/*.tar /tmp/component-inputs/
./prep-source-build.sh --no-sdk --no-bootstrap --no-artifacts --no-prebuilts > preparation.log 2>&1 || { tail -100 preparation.log; exit 1; }
tar -xf /tmp/component-inputs/arcade.tar
tar -xf /tmp/component-inputs/sbrp.tar
./build.sh -sb --projects /source/eng/tools/tasks/Microsoft.DotNet.UnifiedBuild.Tasks/Microsoft.DotNet.UnifiedBuild.Tasks.csproj --configuration Release --arch arm64 /p:Publish=false --source-repository https://github.com/dotnet/dotnet --source-version b0f34d51fccc69fd334253924abd8d6853fad7aa > utility-build.log 2>&1 || { tail -100 utility-build.log; exit 1; }
cat > extract-dependency-tools.proj <<'XML'
<Project>
  <Target Name="Restore">
    <MSBuild Projects="/source/repo-projects/source-build-reference-packages.proj;/source/repo-projects/arcade.proj" Targets="Restore" Properties="BuildProjectReferences=false" BuildInParallel="false" />
  </Target>
  <Target Name="Build">
    <MSBuild Projects="/source/repo-projects/source-build-reference-packages.proj;/source/repo-projects/arcade.proj" Targets="ExtractToolPackage" Properties="BuildProjectReferences=false" BuildInParallel="false" />
  </Target>
</Project>
XML
./build.sh -sb --projects /source/extract-dependency-tools.proj --configuration Release --arch arm64 /p:Publish=false --source-repository https://github.com/dotnet/dotnet --source-version b0f34d51fccc69fd334253924abd8d6853fad7aa > dependency-tools.log 2>&1 || { tail -100 dependency-tools.log; exit 1; }
/usr/bin/time -v -o build.time ./build.sh -sb --projects /source/repo-projects/command-line-api.proj --configuration Release --arch arm64 /p:Publish=false --source-repository https://github.com/dotnet/dotnet --source-version b0f34d51fccc69fd334253924abd8d6853fad7aa /p:BuildProjectReferences=false /p:BuildInParallel=false > build.log 2>&1 || { tail -120 build.log; exit 1; }
mkdir result
cp artifacts/packages/Release/Shipping/command-line-api/System.CommandLine.2.0.0-dev.nupkg result/component.nupkg
tar -cf result.tar preparation.log utility-build.log dependency-tools.log build.log build.time artifacts/log artifacts/obj/manifests/Release/command-line-api
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_action', type=Path)
    parser.add_argument('bundles', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a fresh output archive')
    with tarfile.open(args.source_action / 'sources.tar') as original, tarfile.open(args.output, 'w') as archive:
        for entry in original:
            if entry.name == 'build-native.sh':
                continue
            archive.addfile(entry, original.extractfile(entry) if entry.isfile() else None)
        data = SCRIPT.encode()
        entry = tarfile.TarInfo('build-native.sh')
        entry.size, entry.mode = len(data), 0o644
        archive.addfile(normalize(entry), io.BytesIO(data))
        # The script moves explicit dependency bundles outside the source tree
        # before upstream preparation removes checked-in binaries.
        for name in ['arcade', 'sbrp']:
            archive.add(args.bundles / (name + '.tar'), arcname='prereqs/component-inputs/' + name + '.tar', filter=normalize)


if __name__ == '__main__':
    main()
