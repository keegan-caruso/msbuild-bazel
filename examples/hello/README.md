# Hello: library, application and test

This is a small source-consumption example with no NuGet package dependencies.
`Library` exports a message; `App` prints and checks it. The same program is an
executable Bazel test: a nonzero process exit fails the test.

From the rules repository root, with Bazelisk available (or after
[developer setup](../../docs/development.md)):

```sh
python3 examples/hello/create.py /tmp/rules-msbuild-hello
export RULES_MSBUILD_BAZEL="${RULES_MSBUILD_BAZEL:-$PWD/scripts/bazel-launcher.sh}"
cd /tmp/rules-msbuild-hello
"$RULES_MSBUILD_BAZEL" run //App
"$RULES_MSBUILD_BAZEL" test //App:Tests
```

Expected output: `Hello from MSBuild and Bazel`; the test passes. The destination
must not exist. Bazel reads the copied `global.json`, downloads the verified SDK,
builds the runner, and uses the SDK's bundled runtime. No local SDK installation
or manual runner build is needed. The script only copies example sources and
writes the module declaration; it is not part of build execution. The generated
rules dependency points at this checkout.

Read the generated `MODULE.bazel` and root `BUILD.bazel`, then the checked-in
`Library/BUILD.bazel` and `App/BUILD.bazel`. ProjectReference and Bazel dependency
edges must agree. These rules do not infer sources or project dependencies.

To exercise invalidation, change the string returned by `Library/Message.cs`:
`bazel run //App` prints the new value and exits unsuccessfully because the check
still expects the old value. `bazel test //App:Tests` must fail even though the
library's public API did not change. Update the expected string in `App/Program.cs`
to make the test pass again.

This example uses local compilation. Consult the [worker guide](../../docs/explicit-linux-workers.md),
[test API](../../docs/bazel-test.md) and [remote execution guide](../../docs/remote-execution.md)
for those separate configurations and qualification boundaries.
