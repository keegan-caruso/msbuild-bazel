# Friend assemblies and reference-cache invalidation

The current rules support the qualified `InternalsVisibleTo` slice through normal
SDK/Roslyn behavior. No production rule or runner changes were needed.

Keep the attribute in declared source, or use the SDK's `InternalsVisibleTo` item
in the original project. The consumer's **assembly name**, not its Bazel label,
must match the friend grant. Set `assembly_name` when it differs from the project
filename. Strong-named friends require the full public key. Declare the signing
key as an input; this fixture uses `msbuild_items(item_type = "None", ...)`.

Compilation consumes Roslyn's reference assembly, including friend-visible
internal metadata. Test execution consumes the implementation/runtime closure.
A body-only change can therefore reuse the friend's compilation while executing
its test against new behavior. One reference output is shared by all consumers;
internal API changes may also invalidate non-friend compilations conservatively.

## Reproduction

Build the runner, then run the standalone fixture in a fresh directory in the
qualified Linux ARM64 worker environment:

```sh
export RULES_MSBUILD_DOTNET_ROOT=/path/to/dotnet
export RULES_MSBUILD_BAZEL=/path/to/bazel
bash scripts/dotnet.sh build tools/ExplicitBuild -c Release
python3 tests/explicit_msbuild/internals_visible_to.py /tmp/fresh-ivt
```

The fixture uses three tiny SDK projects and no external packages. The friend
has a Bazel label and csproj filename different from its assembly identity.
Its executable test asserts internal method, constant and generic behavior and
writes the hash of the implementation DLL actually loaded. Signing keys are
created as disposable fixture data, not checked into the repository.

## Results

All **24 cases passed their expected success/failure assertions on each of Bazel
9.2.0 and 8.8.0** (48 total), using SDK 10.0.400 on Linux ARM64. Nine ordinary
MSBuild compilation controls passed per version. See the
[machine-readable evidence](internals-visible-to-evidence.json).
The first 8.8 attempt was blocked by an HTTP 500 while fetching rules_pkg; the
fresh-directory retry completed the full suite.

## Qualified controls

- Friend access succeeds; a non-friend fails with `CS0122`.
- Unchanged builds reuse compilation and test results.
- Internal body edits preserve the reference DLL hash. Only the library compiles;
  the friend's existing test executes and fails on the changed behavior.
- Internal signature edits change reference bytes and recompile the friend,
  producing the expected `CS7036` diagnostic.
- Internal constant changes recompile the friend. Its test sees the new inlined
  constant and fails, proving the previous compiled constant was not reused.
- Internal generic constraint changes recompile the friend and produce `CS0453`.
- Removing or renaming the friend grant changes the reference and causes `CS0122`.
- Both source attributes and the SDK project item grant access correctly.
- Strong-named friends compile and execute. Replacing only the consumer's signing
  key invalidates its compilation and produces `CS0281`.
- Ordinary `dotnet build` controls independently confirm baseline, SDK-item,
  signed and negative access/signature/constraint/key behavior.
- After deleting producer sources and output base, a relocated workspace with a
  fresh Bazel output base recovers both assemblies from disk cache and **forces
  actual test execution**. The loaded implementation hash matches the producer.
  A subsequent body edit compiles only the library and fails the executed test;
  changing the grant still rejects compilation.

The harness explicitly requests reference output groups so the reference-byte
oracle remains available even when consumer compilation is recovered from cache.
Raw logs, Bazel execution logs and build events accompany `results.json`.

This is isolated-worker Linux ARM64 and producer-deleted **local disk-cache**
qualification. It is not a new independent-machine/HTTP-cache, Windows, or
cross-architecture claim. General test protocol and HTTP recovery evidence lives
in [Bazel test execution](bazel-test.md).
