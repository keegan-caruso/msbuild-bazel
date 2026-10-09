#!/usr/bin/env bash
set -euo pipefail
real_metadata=$(realpath "$SDK_POLICY_METADATA")
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
cp MODULE.bazel original.module
cp BUILD.bazel original.build
cp global.json original.global
python3 - <<'PY'
import hashlib,json,tarfile
from pathlib import Path
versions=['9.0.203-preview.2','9.0.203-preview.10','10.0.100','10.0.101','10.0.109','10.0.200','10.0.204-preview.1','10.0.204','11.0.100']
root=Path.cwd(); releases=[]; module='''bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path="../msbuild-bazel")
dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")
'''
for version in versions:
    layout=root/'archive'/version
    (layout/'sdk'/version).mkdir(parents=True)
    (layout/'shared/Microsoft.NETCore.App/10.0.0').mkdir(parents=True)
    (layout/'dotnet').write_text('#!/bin/sh\nexit 0\n');(layout/'dotnet').chmod(0o755)
    archive=root/(version+'.tar.gz')
    with tarfile.open(archive,'w:gz') as tar:tar.add(layout,arcname='.')
    sdk={'version':version,'runtime-version':'10.0.0','files':[
        {'rid':rid,'name':'dotnet-sdk-'+rid+'.tar.gz','url':archive.as_uri(),'hash':hashlib.sha512(archive.read_bytes()).hexdigest()}
        for rid in ['linux-arm64','linux-x64']]}
    releases.append({'sdk':sdk,'sdks':[sdk]}) # Real metadata repeats the latest SDK.
(root/'policy-metadata.json').write_text(json.dumps({'releases':releases}))
cases=[
    ('patch','10.0.100','patch',True,'10.0.100'),
    ('fallback','10.0.102','patch',True,'10.0.109'),
    ('latest_patch','10.0.100','latestPatch',True,'10.0.109'),
    ('latest_feature','10.0.100','latestFeature',False,'10.0.204'),
    ('preview','10.0.100','latestFeature',True,'10.0.204'),
    ('preview_patch','9.0.203-preview.2','latestPatch',True,'9.0.203-preview.10'),
    ('stable_patch','10.0.204-preview.1','latestPatch',True,'10.0.204'),
    ('exact','10.0.100','disable',True,'10.0.100')]
expected={}
for name,version,policy,preview,selected in cases:
    pin=name+'.json';(root/pin).write_text(json.dumps({'sdk':{'version':version,'rollForward':policy,'allowPrerelease':preview}}))
    module+='dotnet.sdk(name='+json.dumps(name)+',global_json="//:'+pin+'",platforms=["linux-arm64"],metadata_urls=['+json.dumps((root/'policy-metadata.json').as_uri())+'])\nuse_repo(dotnet,'+json.dumps(name)+')\n'
    if policy!='disable':expected[json.dumps([version,policy,preview,[(root/'policy-metadata.json').as_uri()]],separators=(',',':'))]=selected
(root/'expected.json').write_text(json.dumps(expected))
(root/'MODULE.bazel').write_text(module)
(root/'BUILD.bazel').write_text('exports_files(glob(["*.json"]))')
PY
bazel build @latest_patch//:files @preview//:files
check_facts() {
    python3 - <<'PY'
import json
from pathlib import Path
facts=next(v for v in json.loads(Path('MODULE.bazel.lock').read_text())['facts'].values() if 'sdk-policy-v1' in v)
assert facts['sdk-policy-v1']==json.loads(Path('expected.json').read_text()),facts
assert '10.0.109' in {json.loads(k)[0] for k in facts['sdk-v1']},facts
PY
}
check_facts
cp policy-metadata.json original.metadata
# Publishing a newer patch does not silently change the committed resolution.
python3 - <<'PY'
import json
from pathlib import Path
p=Path('policy-metadata.json');data=json.loads(p.read_text())
sdk=dict(data['releases'][0]['sdk'],version='10.0.110')
data['releases'].append({'sdk':sdk});p.write_text(json.dumps(data))
PY
printf '\n# Force reevaluation with newer metadata available.\n' >> "$scratch/msbuild-bazel/msbuild/private/sdk_metadata.bzl"
bazel build @latest_patch//:files
check_facts
# Platform expansion must acquire the already-selected SDK, never reselect.
sed -i 's/platforms=\["linux-arm64"\]/platforms=["linux-arm64","linux-x64"]/' MODULE.bazel
bazel build @latest_patch//:files
check_facts
bazel shutdown
rm policy-metadata.json
mkdir "$scratch/recovery"
cp MODULE.bazel MODULE.bazel.lock BUILD.bazel ./*.json "$scratch/recovery/"
(
    cd "$scratch/recovery"
    "$BIT_BAZEL_BINARY" --batch --ignore_all_rc_files --output_base="$scratch/recovery-base" build @latest_patch//:files --lockfile_mode=error
)
# Policy changes are new selections and cannot use stale facts in strict mode.
sed -i 's/latestPatch/latestFeature/' latest_patch.json
if bazel build @latest_patch//:files --lockfile_mode=error > "$TEST_TMPDIR/stale.log" 2>&1; then
    echo 'Changed policy accepted stale lock' >&2; exit 1
fi
assert_contains "$TEST_TMPDIR/stale.log" 'lockfile'
sed -i 's/latestFeature/latestPatch/' latest_patch.json
# Old exact SDK facts migrate without metadata; an invalid locked choice fails.
python3 - <<'PY'
import json
from pathlib import Path
p=Path('MODULE.bazel.lock');lock=json.loads(p.read_text())
facts=next(v for v in lock['facts'].values() if 'sdk-policy-v1' in v)
for key in list(facts['sdk-policy-v1']):
    if json.loads(key)[1]=='patch' and json.loads(key)[0]=='10.0.100':del facts['sdk-policy-v1'][key]
lock['moduleExtensions']={};p.write_text(json.dumps(lock))
PY
bazel query @patch//:all
check_facts
cp MODULE.bazel.lock valid.lock
python3 - <<'PY'
import json
from pathlib import Path
p=Path('MODULE.bazel.lock');lock=json.loads(p.read_text())
facts=next(v for v in lock['facts'].values() if 'sdk-policy-v1' in v)
for key in facts['sdk-policy-v1']:
    if json.loads(key)[1]=='latestPatch':facts['sdk-policy-v1'][key]='11.0.100'
lock['moduleExtensions']={};p.write_text(json.dumps(lock))
PY
if bazel query @latest_patch//:all > "$TEST_TMPDIR/invalid.log" 2>&1; then echo 'Invalid locked policy accepted' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/invalid.log" 'SDK selection does not satisfy global.json'
# Explicit refresh removes only the policy decision, preserving archive facts.
cp valid.lock MODULE.bazel.lock
cp original.metadata policy-metadata.json
python3 - <<'PY'
import json
from pathlib import Path
p=Path('policy-metadata.json');metadata=json.loads(p.read_text())
sdk=dict(metadata['releases'][0]['sdk'],version='10.0.110')
metadata['releases'].append({'sdk':sdk});p.write_text(json.dumps(metadata))
p=Path('MODULE.bazel.lock');lock=json.loads(p.read_text())
facts=next(v for v in lock['facts'].values() if 'sdk-policy-v1' in v)
for key in list(facts['sdk-policy-v1']):
    if json.loads(key)[:2]==['10.0.100','latestPatch']:del facts['sdk-policy-v1'][key]
lock['moduleExtensions']={};p.write_text(json.dumps(lock))
PY
bazel query @latest_patch//:all
python3 - <<'PY'
import json
from pathlib import Path
facts=next(v for v in json.loads(Path('MODULE.bazel.lock').read_text())['facts'].values() if 'sdk-policy-v1' in v)
assert any(json.loads(k)[:2]==['10.0.100','latestPatch'] and v=='10.0.110' for k,v in facts['sdk-policy-v1'].items())
PY

# Real SDK: the requested lower bound differs from the acquired/used SDK version.
cp original.module MODULE.bazel
cp original.build BUILD.bazel
cp original.global global.json
python3 - "$real_metadata" <<'PY'
import json,sys
from pathlib import Path
p=Path('MODULE.bazel');p.write_text(p.read_text().replace('global_json = "//:global.json"','global_json = "//:global.json", metadata_urls = ['+json.dumps(Path(sys.argv[1]).as_uri())+']'))
Path('global.json').write_text(json.dumps({'sdk':{'version':'9.0.300','rollForward':'latestPatch','allowPrerelease':False}}))
for p in Path('.').glob('*/*.csproj'):p.write_text(p.read_text().replace('net10.0','net9.0'))
PY
bazel run //:sync
bazel run //:sync -- --check
bazel run //:app > "$TEST_TMPDIR/app.log"
assert_contains "$TEST_TMPDIR/app.log" 'Hello from MSBuild and Bazel'
assert_contains graph.generated.json '"SdkVersion": "9.0.318"'
bazel test //:tests --test_output=errors
echo 'PASS: SDK policies, locked version reuse, platform expansion, strict recovery and real SDK sync/run/test'
