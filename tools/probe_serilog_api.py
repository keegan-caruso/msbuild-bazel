"""Standalone pinned public API comparison; does not run upstream xunit tests."""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
HELPER = ROOT / 'SerilogApiOracle'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(source, packages, assembly, output, dotnet_root):
    source, packages, assembly, output = map(lambda p: Path(p).resolve(), (source, packages, assembly, output))
    if output.exists():
        raise ValueError('output must be a fresh evidence directory')
    pins = json.loads((HELPER / 'pins.json').read_text())
    # The three exact upstream files define this oracle; the checkout may also be
    # an archive or an ordinary-build workspace without a .git directory.
    for relative, expected in pins['sourceFiles'].items():
        if digest(source / relative) != expected:
            raise ValueError('upstream oracle source differs from pin: ' + relative)
    archives = []
    for identity, expected in pins['packages'].items():
        archive = packages / identity / (identity.replace('/', '.') + '.nupkg')
        if digest(archive) != expected:
            raise ValueError('oracle package archive differs from pin: ' + identity)
        archives.append(archive)
    assembly_hash = digest(assembly)
    output.mkdir(parents=True)
    shutil.copytree(HELPER, output / 'helper', ignore=shutil.ignore_patterns('bin', 'obj'))
    feed = output / 'feed'
    feed.mkdir()
    for archive in archives:
        shutil.copyfile(archive, feed / archive.name)
    # No parent checkout configuration, source mapping or online package feed.
    config = output / 'NuGet.Config'
    config.write_text('<configuration><packageSources><clear /></packageSources></configuration>')
    sdk = Path(dotnet_root).resolve()
    (output / 'global.json').write_text(json.dumps({'sdk': {'version': '10.0.100', 'rollForward': 'disable'}}))
    env = dict(os.environ, DOTNET_ROOT=str(sdk), NUGET_PACKAGES=str(output / 'packages'),
               DOTNET_CLI_HOME=str(output / 'home'), MSBUILDDISABLENODEREUSE='1')

    def run(name, args):
        result = subprocess.run([str(sdk / 'dotnet'), *map(str, args)], cwd=output,
                                env=env, capture_output=True, text=True, timeout=240)
        (output / (name + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(name + ' failed; see ' + str(output / (name + '.log')))

    project = output / 'helper/SerilogApiOracle.csproj'
    run('restore', ['restore', project, '--configfile', config, '--source', feed, '--nologo', '-nodeReuse:false'])
    run('build', ['build', project, '-c', 'Release', '--no-restore', '--nologo', '-nodeReuse:false'])
    actual_path = output / 'Serilog.actual.txt'
    run('generate', [output / 'helper/bin/Release/net10.0/SerilogApiOracle.dll', assembly, actual_path])
    approved_path = source / 'test/Serilog.ApprovalTests/Serilog.approved.txt'
    shutil.copyfile(approved_path, output / 'Serilog.approved.txt')
    # Approval comparison permits platform line endings and a final newline only;
    # whitespace and text inside lines remain significant.
    actual = actual_path.read_text().replace('\r\n', '\n').rstrip('\n')
    approved = approved_path.read_text().replace('\r\n', '\n').rstrip('\n')
    passed = actual == approved
    diff = ''.join(difflib.unified_diff(approved.splitlines(True), actual.splitlines(True),
                                      fromfile='approved', tofile='actual'))
    (output / 'public-api.diff').write_text(diff)
    if digest(assembly) != assembly_hash:
        raise RuntimeError('supplied assembly changed during API generation')
    report = dict(schemaVersion=1, passed=passed, scope='standalone-public-api-oracle',
                  upstreamRevision=pins['revision'], assembly=str(assembly), assemblySha256=assembly_hash,
                  actualSha256=digest(actual_path), approvedSha256=digest(approved_path),
                  options=dict(includeAssemblyAttributes=False, excludeAttributes=['System.Diagnostics.DebuggerDisplayAttribute']),
                  packageArchiveSha256=pins['packages'], sourceSha256=pins['sourceFiles'],
                  comparison='exact text except CRLF/LF and trailing newlines',
                  upstreamTestProjectExecuted=False)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'packages', 'assembly', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--dotnet-root', default=os.environ.get('SPIKE_DOTNET_ROOT'))
    args = parser.parse_args()
    if not args.dotnet_root:
        parser.error('--dotnet-root or SPIKE_DOTNET_ROOT is required')
    report = compare(args.source, args.packages, args.assembly, args.output, args.dotnet_root)
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
