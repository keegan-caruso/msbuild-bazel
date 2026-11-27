#!/usr/bin/env bash
# Sourced by integration runners. Only declared runfiles enter the scratch tree.
set -euo pipefail
case "$(uname -s)/$(uname -m)" in
    Linux/aarch64) export SDK_TEST_RID=linux-arm64 ;;
    Linux/x86_64) export SDK_TEST_RID=linux-x64 ;;
    Darwin/arm64) export SDK_TEST_RID=osx-arm64 ;;
    Darwin/x86_64) export SDK_TEST_RID=osx-x64 ;;
    MINGW*ARM64/x86_64|MSYS_NT*ARM64/x86_64|MINGW*/aarch64|MSYS_NT*/aarch64|MINGW*/arm64|MSYS_NT*/arm64) export SDK_TEST_RID=win-arm64 ;;
    MINGW*/x86_64|MSYS_NT*/x86_64) export SDK_TEST_RID=win-x64 ;;
    *) echo 'Unsupported integration fixture platform.' >&2; exit 1 ;;
esac
# TEST_TMPDIR is nested below the rules checkout's execroot. MSBuild would discover
# its ancestor .editorconfig there, so put consumer sources outside that tree.
scratch=$(mktemp -d /tmp/msbuild-bazel-integration.XXXXXX)
mkdir -p "$scratch/consumer" "$scratch/msbuild-bazel"
cp -RL "$BIT_WORKSPACE_DIR/." "$scratch/consumer/"
tar -xf "$RULES_ARCHIVE" -C "$scratch/msbuild-bazel"
if [[ -n "$(find "$scratch/msbuild-bazel" -type l -print -quit)" ]]; then
    echo 'Rules archive must contain independent files, not checkout symlinks.' >&2
    rm -rf "$scratch"
    exit 1
fi
# Keep the public example's ../msbuild-bazel override unchanged.
cd "$scratch/consumer"
unset RULES_MSBUILD_PROJECT_CACHE_URL RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN
# Nested builds own a separate server and output base; always stop it on exit.
bazel() {
    # macOS ships Bash 3.2, where an empty array is unset under set -u.
    local args=(--nosystem_rc --nohome_rc --noworkspace_rc "--output_base=$scratch/bazel" "$1")
    case "$1" in
        build|run|test)
            if [[ -n "${RULES_MSBUILD_TEST_REPOSITORY_CACHE:-}" ]]; then
                args+=("--repository_cache=$RULES_MSBUILD_TEST_REPOSITORY_CACHE")
            fi ;;
    esac
    "$BIT_BAZEL_BINARY" "${args[@]}" "${@:2}"
}
cleanup() {
    bazel shutdown >/dev/null 2>&1 || true
    # Bazel publishes read-only output directories. Make only our scratch
    # directories writable; find does not follow external/toolchain symlinks.
    find "$scratch" -type d -exec chmod u+w {} +
    rm -rf "$scratch"
}
trap cleanup EXIT
assert_contains() {
    if ! grep -Fq -- "$2" "$1"; then cat "$1" >&2; echo "Missing: $2" >&2; exit 1; fi
}

# Assert exact mnemonic counts and real whole-action remote hits.
assert_remote_hits() {
    python3 - "$@" <<'PY'
import json,sys
expected=dict(expectation.split('=') for expectation in sys.argv[2:])
selected={mnemonic:[] for mnemonic in expected}
data=open(sys.argv[1]).read();decoder=json.JSONDecoder();position=0
while position<len(data):
    while position<len(data) and data[position].isspace():position+=1
    if position==len(data):break
    action,position=decoder.raw_decode(data,position)
    matches=selected.get(action.get('mnemonic'))
    if matches is not None:matches.append(action)
for mnemonic,count in expected.items():
    matches=selected[mnemonic]
    assert len(matches)==int(count) and all(action.get('cacheHit') and action.get('runner')=='remote cache hit' for action in matches),(mnemonic,count,matches)
PY
}

# Preserve each case's report, prepared-Restore check and timing row.
assert_build_report() {
    python3 - "$@" "$TEST_TMPDIR" <<'PY'
import json,sys,time
from pathlib import Path
report,row,hits,misses,start,logs=sys.argv[1:]
result=json.load(open(report))
assert (result['hits'],result['misses'])==(int(hits),int(misses)),(row,result)
assert result['preparedRestore']
Path(logs,row+'-report.json').write_text(json.dumps(result))
with open(Path(logs,'timings.tsv'),'a') as output:
    output.write(f'{row}\t{time.monotonic()-float(start):.3f}\t{hits}\t{misses}\n')
PY
}

# Retain the exact selected-file order and hashes used by raw/product parity.
assert_product_parity() {
    local expected="$1" actual="$2" root="$3"; shift 3
    (cd "$root"; sha256sum "$@") > "$actual"
    cmp "$expected" "$actual"
}

# SDK publish endpoints contain build-time Last-Modified headers. Raw/cold
# rebuilds compare those timestamps structurally; actual cache hits stay byte-exact.
assert_static_asset_parity() {
    python3 - "$@" <<'PY'
import hashlib,json,sys
from email.utils import parsedate_to_datetime
from pathlib import Path
expected,actual,expected_endpoints,actual_endpoints,logical=sys.argv[1:]
def inventory(path):
    entries=[line.split('  ',1) for line in Path(path).read_text().splitlines()]
    endpoints=[digest for digest,name in entries if name==logical]
    assert len(endpoints)==1,(path,logical,endpoints)
    return [(digest,name) for digest,name in entries if name!=logical],endpoints[0]
def manifest(path,digest):
    content=Path(path).read_bytes()
    assert hashlib.sha256(content).hexdigest()==digest,(path,digest)
    data=json.loads(content);count=0
    for endpoint in data['Endpoints']:
        for header in endpoint['ResponseHeaders']:
            if header['Name']=='Last-Modified':
                assert parsedate_to_datetime(header['Value']).tzinfo is not None
                header['Value']='<timestamp>';count+=1
    assert count>0,path
    return data
left,left_digest=inventory(expected);right,right_digest=inventory(actual)
assert left==right,(expected,actual,left,right)
assert manifest(expected_endpoints,left_digest)==manifest(actual_endpoints,right_digest)
PY
}
