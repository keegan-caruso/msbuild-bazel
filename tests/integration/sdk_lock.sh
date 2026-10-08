#!/usr/bin/env bash
set -euo pipefail
sdk_qualification_metadata=$(realpath "$SDK_QUALIFICATION_METADATA")
for binary in $BAZEL_8; do
    if [[ "$binary" == */bazel_binary ]]; then bazel_8=$(realpath "$binary"); fi
done
for binary in $BAZEL_9; do
    if [[ "$binary" == */bazel_binary ]]; then bazel_9=$(realpath "$binary"); fi
done
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
cp MODULE.bazel original.module
cp BUILD.bazel original.build
cp global.json original.global

mkdir -p archive/sdk/42.0.123 archive/shared/Microsoft.NETCore.App/42.0.7
printf '#!/bin/sh\nexit 0\n' > archive/dotnet
chmod +x archive/dotnet
tar -czf supplied.tar.gz -C archive .
cp supplied.tar.gz good.tar.gz
python3 - <<'PY'
import hashlib, json
from pathlib import Path
root = Path.cwd()
archive = root / 'supplied.tar.gz'
metadata = {'releases': [{'sdk': {'version': '42.0.123', 'runtime-version': '42.0.7', 'files': [
    {'rid': rid, 'name': 'dotnet-sdk-' + rid + '.tar.gz', 'url': archive.as_uri(), 'hash': hashlib.sha512(archive.read_bytes()).hexdigest()}
    for rid in ['linux-arm64', 'linux-x64']
]}}]}
(root / 'releases.json').write_text(json.dumps(metadata))
(root / 'global.json').write_text('{"sdk":{"version":"42.0.123","rollForward":"disable"}}')
(root / 'MODULE.bazel').write_text('''module(name="sdk_lock_fixture")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path="../msbuild-bazel")
dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")
dotnet.sdk(name="supplied",global_json="//:global.json",platforms=["linux-arm64"],metadata_urls=[''' + json.dumps((root / 'releases.json').as_uri()) + '''])
use_repo(dotnet,"supplied")
''')
PY
echo 'exports_files(["global.json"])' > BUILD.bazel
bazel build @supplied//:files
python3 - <<'PY'
import base64, hashlib, json
from pathlib import Path
lock = json.loads(Path('MODULE.bazel.lock').read_text())
facts = next(item['sdk-v1'] for item in lock['facts'].values() if 'sdk-v1' in item)
sdk = next(iter(facts.values()))
assert sdk['runtime'] == '42.0.7'
assert sdk['platforms']['linux-arm64']['integrity'] == 'sha512-' + base64.b64encode(hashlib.sha512(Path('supplied.tar.gz').read_bytes()).digest()).decode()
PY
fresh() {
    "$BIT_BAZEL_BINARY" --batch --nosystem_rc --nohome_rc --noworkspace_rc --output_base="$1" "${@:2}"
}
expect_failure() {
    if bazel "$@" > "$TEST_TMPDIR/failure.log" 2>&1; then
        cat "$TEST_TMPDIR/failure.log" >&2; echo 'Expected failure' >&2; exit 1
    fi
}

# Adding a platform extends the existing selection without replacing its hashes.
sed -i 's/platforms=\["linux-arm64"\]/platforms=["linux-arm64","linux-x64"]/' MODULE.bazel
bazel build @supplied//:files
python3 - <<'PY'
import json
from pathlib import Path
lock = json.loads(Path('MODULE.bazel.lock').read_text())
facts = next(item['sdk-v1'] for item in lock['facts'].values() if 'sdk-v1' in item)
assert sorted(next(iter(facts.values()))['platforms']) == ['linux-arm64', 'linux-x64']
PY
# Fresh clone/base uses the committed resolution, with metadata no longer present.
mkdir "$scratch/clone"
cp MODULE.bazel MODULE.bazel.lock BUILD.bazel global.json "$scratch/clone/"
mv releases.json unavailable.json
(
    cd "$scratch/clone"
    fresh "$scratch/clone-base" build @supplied//:files --lockfile_mode=error
)
# Switching Bazel versions may add registry entries; SDK facts survive unchanged.
for other_bazel in "$bazel_8" "$bazel_9"; do
    (
        cd "$scratch/clone"
        cross_base="$scratch/cross-$(basename "$(dirname "$other_bazel")")"
        "$other_bazel" --batch --nosystem_rc --nohome_rc --noworkspace_rc --output_base="$cross_base-update" build @supplied//:files
        "$other_bazel" --batch --nosystem_rc --nohome_rc --noworkspace_rc --output_base="$cross_base-strict" build @supplied//:files --lockfile_mode=error
    )
done
# Force extension reevaluation without changing the selected version/source.
python3 - <<'PY'
from pathlib import Path
p = Path('MODULE.bazel')
s = p.read_text()
declaration = next(line for line in s.splitlines() if line.startswith('dotnet.sdk('))
p.write_text(s + declaration.replace('name="supplied"', 'name="second"') + '\nuse_repo(dotnet,"second")\n')
PY
bazel build @second//:files
# Even a changed extension implementation must reuse persisted facts.
printf '\n# Force extension reevaluation for the recovery control.\n' >> "$scratch/msbuild-bazel/msbuild/private/sdk_metadata.bzl"
bazel build @supplied//:files
sed -i 's/42.0.123/42.0.124/' global.json
expect_failure build @supplied//:files --lockfile_mode=error
assert_contains "$TEST_TMPDIR/failure.log" 'lockfile'
mv unavailable.json releases.json
expect_failure build @supplied//:files
assert_contains "$TEST_TMPDIR/failure.log" 'Release metadata must identify exactly one SDK'
python3 - <<'PY'
import json
from pathlib import Path
p = Path('releases.json')
metadata = json.loads(p.read_text())
metadata['releases'][0]['sdk']['version'] = '42.0.124'
metadata['releases'][0]['sdk']['files'][0]['hash'] = 'bad'
Path('bad-releases.json').write_text(json.dumps(metadata))
m = Path('MODULE.bazel'); m.write_text(m.read_text().replace('/releases.json', '/bad-releases.json'))
PY
expect_failure build @supplied//:files
assert_contains "$TEST_TMPDIR/failure.log" 'Release metadata SDK hash must be SHA-512 hex'
sed -i 's/42.0.124/42.0.123/' global.json
sed -i 's@/bad-releases.json@/releases.json@g' MODULE.bazel
bazel build @supplied//:files
# A changed remote archive cannot pass the pinned hash on a fresh acquisition.
cp MODULE.bazel MODULE.bazel.lock "$scratch/clone/"
printf corrupt > supplied.tar.gz
if (cd "$scratch/clone"; fresh "$scratch/corrupt-base" build @supplied//:files --lockfile_mode=error --repository_cache="$scratch/empty-cache") > "$TEST_TMPDIR/failure.log" 2>&1; then
    echo 'Corrupt SDK archive passed' >&2; exit 1
fi
assert_contains "$TEST_TMPDIR/failure.log" 'Checksum'
cp good.tar.gz supplied.tar.gz

python3 - <<'PY'
import base64, hashlib, json
from pathlib import Path
archive = Path('supplied.tar.gz').resolve()
p = Path('MODULE.bazel')
p.write_text(p.read_text() + '\ndotnet.sdk_archive(name="private_sdk",version="42.0.123",runtime_version="42.0.7",platform="linux-arm64",urls=[' + json.dumps(archive.as_uri()) + '],integrity=' + json.dumps('sha512-' + base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()) + ')\nuse_repo(dotnet,"private_sdk")\n')
PY
bazel build @private_sdk//:files
sed -i 's/runtime_version="42.0.7"/runtime_version="42.0.8"/' MODULE.bazel
expect_failure build @private_sdk//:files
assert_contains "$TEST_TMPDIR/failure.log" 'SDK archive is missing declared layout component'
sed -i 's/runtime_version="42.0.8"/runtime_version="42.0.7"/' MODULE.bazel
python3 - <<'PY'
import re
from pathlib import Path
p = Path('MODULE.bazel'); p.write_text(re.sub(r'integrity="[^"]+"', 'integrity=""', p.read_text()))
PY
expect_failure build @private_sdk//:files
assert_contains "$TEST_TMPDIR/failure.log" 'SDK archives require SHA-256 or SHA-512 integrity'

# Real SDK outside the old catalog: automatic resolution, sync, app and tests.
cp original.module MODULE.bazel
cp original.build BUILD.bazel
cp original.global global.json
cp "$sdk_qualification_metadata" sdk-metadata.json
sed -i 's/10.0.400/10.0.302/' global.json
python3 - <<'PY'
import json
from pathlib import Path
p = Path('MODULE.bazel')
p.write_text(p.read_text().replace('global_json = "//:global.json",', 'global_json = "//:global.json",\n    metadata_urls = [' + json.dumps(Path('sdk-metadata.json').resolve().as_uri()) + '],'))
PY
bazel run //:sync
bazel run //:app > "$TEST_TMPDIR/app.log"
assert_contains "$TEST_TMPDIR/app.log" 'Hello from MSBuild and Bazel'
bazel test //:tests --test_output=errors
bazel run //:sync -- --check
assert_contains graph.generated.json '"SdkVersion": "10.0.302"'
rm sdk-metadata.json
mkdir "$scratch/real-clone"
tar -cf "$scratch/clone.tar" App Library Tests MODULE.bazel MODULE.bazel.lock BUILD.bazel global.json graph.generated.json graph.generated.bzl
tar -xf "$scratch/clone.tar" -C "$scratch/real-clone"
(
    cd "$scratch/real-clone"
    fresh "$scratch/real-base" test //:tests --lockfile_mode=error --test_output=errors
)
echo 'PASS: automatic SDK resolution, native lock/facts recovery, pin checks, archive integrity and .NET 10.0.302 app/tests'
