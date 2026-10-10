#!/usr/bin/env bash
# Resolution is explicit; ordinary sync/build consumes committed locks offline.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
python3 - <<'PY'
from pathlib import Path
p=Path('BUILD.bazel');s=p.read_text().replace('"msbuild_sync")','"msbuild_sync", "msbuild_nuget_update")')
if 'name = "update_packages"' not in s:
    s+='\nmsbuild_nuget_update(name = "update_packages", projects = ["Web/Web.csproj", "Tests/Tests.csproj"])\n'
p.write_text(s)
PY
bazel run //:update_packages
bazel run //:update_packages -- --check
python3 - <<'PY'
import json,hashlib
from pathlib import Path
manifest=json.loads(Path('nuget.lock.json').read_text());assert manifest['generatedBy']=='RulesMSBuild.NuGetUpdate'
assert len(manifest['packages'])>=2 and len(manifest['lockFiles'])>=5
assert not list(Path('.').glob('*/obj')) and not list(Path('.').glob('*/bin'))
native=json.loads(Path('Web/packages.lock.json').read_text())['dependencies']['net10.0']
archive=next(p for p in manifest['packages'] if p['id']=='Newtonsoft.Json')
# Signed package locks use NuGet's canonical hash, not the raw archive SHA512.
assert native['Newtonsoft.Json']['contentHash'] != archive['archiveSha512']
p=Path('MODULE.bazel');s=p.read_text().split('http_file =')[0]
if 'msbuild:nuget.bzl' not in s:
    s+='nuget = use_extension("@rules_msbuild//msbuild:nuget.bzl", "nuget")\nnuget.lock(name = "nuget", lockfile = "//:nuget.lock.json")\nuse_repo(nuget, "nuget")\n'
p.write_text(s)
p=Path('BUILD.bazel');s=p.read_text().replace('load(":packages.bzl", "catalog_packages")\n','').replace('catalog_packages()','').replace('package_lock = ":packages"','package_lock = "@nuget//:packages"');p.write_text(s)
PY
bazel run //:sync
bazel run //:sync -- --check
python3 - <<'PY'
import json
from pathlib import Path
m=json.loads(Path('nuget.lock.json').read_text());c=json.loads(Path('graph.generated.json').read_text())
assert set(m['lockFiles']) <= set(c['DefinitionDigests'])
assert set(m['lockFiles']) <= set(c['SharedInputs'])
PY
bazel test //:tests //:web_test //:published_test --remote_cache= --disk_cache= --test_output=errors
# Failed resolution must not publish even the locks from successfully restored roots.
cp Directory.Build.props "$TEST_TMPDIR/props.before"
cp nuget.lock.json "$TEST_TMPDIR/manifest.before"
cp Web/packages.lock.json "$TEST_TMPDIR/web-lock.before"
python3 - <<'PY'
from pathlib import Path
p=Path('Directory.Build.props');p.write_text(p.read_text().replace('</Project>','<ItemGroup><PackageReference Include="RulesMSBuild.NonexistentQualificationPackage" Version="999.0.0"/></ItemGroup></Project>'))
PY
if bazel run //:update_packages > "$TEST_TMPDIR/failed-update.log" 2>&1; then echo 'Missing package update succeeded' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/failed-update.log" 'existing locks were left unchanged'
cmp nuget.lock.json "$TEST_TMPDIR/manifest.before"
cmp Web/packages.lock.json "$TEST_TMPDIR/web-lock.before"
cp "$TEST_TMPDIR/props.before" Directory.Build.props
# Locked offline Restore rejects a corrupt native hash and leaves the contract intact.
cp graph.generated.json "$TEST_TMPDIR/contract.before"
python3 - <<'PY'
import json
from pathlib import Path
p=Path('Web/packages.lock.json');d=json.loads(p.read_text());d['dependencies']['net10.0']['Newtonsoft.Json']['contentHash']='A'*86+'==';p.write_text(json.dumps(d))
PY
if bazel run //:sync > "$TEST_TMPDIR/failed-sync.log" 2>&1; then echo 'Corrupt native lock succeeded' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/failed-sync.log" 'NU1403'
cmp graph.generated.json "$TEST_TMPDIR/contract.before"
cp "$TEST_TMPDIR/web-lock.before" Web/packages.lock.json
bazel run //:sync -- --check
# A malformed archive inventory is rejected before package acquisition.
python3 - <<'PY'
import json
from pathlib import Path
p=Path('nuget.lock.json');d=json.loads(p.read_text());d['packages'][0]['sha256']='bad';p.write_text(json.dumps(d))
PY
if bazel build @nuget//:packages > "$TEST_TMPDIR/failed-manifest.log" 2>&1; then echo 'Malformed SHA256 succeeded' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/failed-manifest.log" 'requires a lowercase SHA256'
cp "$TEST_TMPDIR/manifest.before" nuget.lock.json
echo "PASS: $SDK_TEST_RID explicit NuGet update/check, offline native locks, app/Publish and failure preservation"
