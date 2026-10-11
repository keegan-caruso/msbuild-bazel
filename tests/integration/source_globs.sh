#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

mkdir -p Library/LongDirectoryPrefix
for ((index=0; index<40; index++)); do
    printf -v i '%02d' "$index"
    printf 'public class Source%s { public static int Value() => 0; }\n' "$i" > "Library/LongDirectoryPrefix/Source$i.cs"
done
printf 'using Hello;\nSystem.Console.WriteLine(Message.Text());\nSystem.Console.WriteLine(Source00.Value());\nreturn Message.Text() == "Hello from MSBuild and Bazel" ? 0 : 1;\n' > App/Program.cs
# Build products must never become authored inputs.
mkdir -p Library/bin Library/obj
printf 'not C#\n' > Library/bin/Ignore.cs
printf 'not C#\n' > Library/obj/Ignore.cs
bazel run //:sync
assert_contains graph.generated.bzl '"Library/LongDirectoryPrefix/*.cs"'
bazel run //:sync -- --check
bazel run //:app > "$TEST_TMPDIR/app.log"
assert_contains "$TEST_TMPDIR/app.log" 'Hello from MSBuild and Bazel'
grep -Fxq '0' "$TEST_TMPDIR/app.log"

# Content edits keep membership; added/removed/renamed files require sync.
printf 'public class Source00 { public static int Value() => 1; }\n' > Library/LongDirectoryPrefix/Source00.cs
bazel run //:app > "$TEST_TMPDIR/body.log"
assert_contains "$TEST_TMPDIR/body.log" 'Hello from MSBuild and Bazel'
grep -Fxq '1' "$TEST_TMPDIR/body.log"
printf 'public class Extra {}\n' > Library/LongDirectoryPrefix/Extra.cs
if bazel build //:graph > "$TEST_TMPDIR/add.log" 2>&1; then exit 1; fi
assert_contains "$TEST_TMPDIR/add.log" 'Source glob membership changed; rerun sync'
bazel run //:sync
bazel run //:app > "$TEST_TMPDIR/added.log"
assert_contains "$TEST_TMPDIR/added.log" 'Hello from MSBuild and Bazel'

# Equal-count replacement must also fail before any graph execution.
mv Library/LongDirectoryPrefix/Extra.cs Library/LongDirectoryPrefix/Renamed.cs
if bazel build //:graph > "$TEST_TMPDIR/rename.log" 2>&1; then exit 1; fi
assert_contains "$TEST_TMPDIR/rename.log" 'Source glob membership changed; rerun sync'
bazel run //:sync
rm Library/LongDirectoryPrefix/Renamed.cs
if bazel build //:graph > "$TEST_TMPDIR/remove.log" 2>&1; then exit 1; fi
assert_contains "$TEST_TMPDIR/remove.log" 'Source glob membership changed; rerun sync'
bazel run //:sync
bazel test //:tests --test_output=errors
bazel run //:sync -- --check
# Generated globs use repository-relative paths when consumed from another module.
python3 - "$TEST_TMPDIR/external-globs" <<'PY'
import json,sys,shutil
from pathlib import Path
root=Path(sys.argv[1]);(root/'Sources').mkdir(parents=True)
(root/'MODULE.bazel').write_text('module(name="external_globs")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n')
(root/'Sources/Value.cs').write_text('public class Value {}')
for name in ['App','Library','Tests']:
    shutil.copytree(name,root/name,ignore=shutil.ignore_patterns('bin','obj'))
for name in ['Directory.Build.props','NuGet.Config','global.json','graph.generated.bzl','graph.generated.json']:
    if Path(name).is_file(): shutil.copyfile(name,root/name)
(root/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:sync.bzl","sync_source_globs")\nsync_source_globs(name="sources",globs={"Sources/*.cs":["Value.cs"]})\nload(":graph.generated.bzl","app_graph")\napp_graph(name="graph")\nexports_files(["Sources/Value.cs"])\n')
p=Path('MODULE.bazel');p.write_text(p.read_text()+'\nbazel_dep(name="external_globs",version="0.0.0")\nlocal_path_override(module_name="external_globs",path='+json.dumps(str(root))+')\n')
PY
bazel build @external_globs//:sources @external_globs//:graph
cat >> BUILD.bazel <<'BZL'
load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph")
msbuild_graph(name="foreign_sources",runner=":graph_runner",contract="graph.generated.json",srcs=["@external_globs//:Sources/Value.cs"])
BZL
if bazel build //:foreign_sources > "$TEST_TMPDIR/foreign.log" 2>&1; then exit 1; fi
assert_contains "$TEST_TMPDIR/foreign.log" 'Graph sources from other repositories require input_paths'
printf 'public class Added {}\n' > "$TEST_TMPDIR/external-globs/Sources/Added.cs"
if bazel build @external_globs//:sources > "$TEST_TMPDIR/external-added.log" 2>&1; then exit 1; fi
assert_contains "$TEST_TMPDIR/external-added.log" 'Source glob membership changed; rerun sync'
echo 'PASS: local/external source globs, body edits, membership guards and runnable resync'
