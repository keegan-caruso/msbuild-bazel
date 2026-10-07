#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

mkdir -p Library/LongDirectoryPrefix
for i in {00..39}; do
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
echo 'PASS: source globs, body edits, membership guards and runnable resync'
