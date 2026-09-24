# Next work

Use the [current support summary](implementation-plan.md) for what is qualified.
The trackers below describe remaining work, not promises of platform support.

1. **Reduce cold-build overhead — [#13](https://github.com/keegan-caruso/msbuild-bazel/issues/13).**
   The latest single-VM comparison is 301.83 s versus 139.75 s raw build time
   (2.16×), with an 8-GiB VM and a 4096-MB worker budget; restore is separate.
   Stable analyzer groups save about 5% versus matching controls. Compiler work
   remains dominant. See [conditions and evidence](runtime-cold-timing.md).
   Keep warm edits, acquisition and remote recovery separate.

2. **Qualify the first authored JIT test — [#74](https://github.com/keegan-caruso/msbuild-bazel/issues/74).**
   Establish raw bootstrap parity, then declare the shared test dependencies and
   wrapper generator. Preserve the authored exit-code contract. See the
   [observed boundary](runtime-jit-bootstrap.md).
3. **Expand remote execution — [#43](https://github.com/keegan-caruso/msbuild-bazel/issues/43),
   [#44](https://github.com/keegan-caruso/msbuild-bazel/issues/44).**
   SDK-only bootstrap, diamond invalidation, source-content packages and declared
   task controls pass on the SDK-free ARM64 executor with both Bazel baselines.
   Standalone generation, binary/native package inputs and five Avalonia IDLs
   also pass. The [11-project Avalonia theme graph](avalonia-remote-execution.md)
   adds remote compilation, runtime tests and independent recovery. Next expand
   to an authored upstream test suite or a second executor platform.
4. **Make source-dependent tests relocatable — [#9](https://github.com/keegan-caruso/msbuild-bazel/issues/9).**
   Preserve declared baseline/source inputs without relying on embedded absolute
   checkout paths or making the build root writable. Current Serilog, Spectre and
   ASP.NET test failures are described in the [test guide](bazel-test.md).
5. **Finish public-source preparation — [#49](https://github.com/keegan-caruso/msbuild-bazel/issues/49).**
   Review the [publication report](publication-readiness.md), remaining remote
   history and launch settings. Publishing source is separate from runner/BCR distribution.

## Separate qualification tracks

- Native Linux x64 [#56](https://github.com/keegan-caruso/msbuild-bazel/issues/56),
  macOS x64 [#54](https://github.com/keegan-caruso/msbuild-bazel/issues/54), and Windows
  [ARM64 #61](https://github.com/keegan-caruso/msbuild-bazel/issues/61) /
  [x64 #62](https://github.com/keegan-caruso/msbuild-bazel/issues/62).
  Windows also needs a runner sandbox implementation.
- Instrumented coverage [#23](https://github.com/keegan-caruso/msbuild-bazel/issues/23),
  Pack [#25](https://github.com/keegan-caruso/msbuild-bazel/issues/25),
  Publish [#29](https://github.com/keegan-caruso/msbuild-bazel/issues/29), and
  NativeAOT [#32](https://github.com/keegan-caruso/msbuild-bazel/issues/32).
- NBGV production context [#27](https://github.com/keegan-caruso/msbuild-bazel/issues/27),
  wider restore metadata [#28](https://github.com/keegan-caruso/msbuild-bazel/issues/28),
  Blazor/WASM [#37](https://github.com/keegan-caruso/msbuild-bazel/issues/37), desktop and
  languages [#38](https://github.com/keegan-caruso/msbuild-bazel/issues/38), Aspire
  [#40](https://github.com/keegan-caruso/msbuild-bazel/issues/40), and IDE workflows
  [#45](https://github.com/keegan-caruso/msbuild-bazel/issues/45).

Keep production rules generic. Prove missing behavior with small synthetics before
expanding a pinned upstream slice. CI remains manual-only. The retired milestone
system is preserved in [history](history.md).
