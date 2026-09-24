# Avalonia HTTP cache portability across Linux containers

The [actual theme graph](avalonia-xaml-subset.md), plus actual Native IDL generation,
recovers across independent Ubuntu 22.04 ARM64 Apple containers on the same Mac.
This is HTTP action-cache qualification, not remote execution or a WAN benchmark.

## Isolation and inputs

- Bazel 9.2.0, SDK 10.0.400, four CPUs per container.
- Pinned bazel-remote 2.6.2 served HTTP on the private container bridge. Its binary
  SHA-256 matches scripts/bazel-remote.json. The cache started empty.
- Producer checkout: `/tmp/avalonia-real-1/bazel`, rules at `/workspace`.
- Consumer checkout: `/work/relocated-avalonia`, rules at `/opt/consumer/rules`.
- Consumer uses a fresh image, no producer filesystem mounts, identical copied
  runner bytes, and a fresh Bazel output base/user root for every control. The SDK
  remains at the qualified worker's fixed location. The worker's internal paths
  are content-addressed as before.
- Only source files, locked archives, tool payloads and repository-download cache
  are copied. No producer action cache or compiled project outputs are copied.
- Disk cache is disabled. Consumers cannot upload action results. All outputs are
  downloaded for byte verification (`--remote_download_outputs=all`).
- The producer container was stopped before the final baseline and edited-version
  recovery checks. The HTTP service continued independently on the host.

The extra IDL action uses the unmodified Avalonia Native avn.idl and pinned
MicroCom 0.11.0 task via the generic generation rule. It is a separate generation
control; this does not claim compilation of the native platform backend.

## Measured results

| Case | Assembly/generator actions executed | HTTP hits among those actions |
| --- | ---: | ---: |
| Fresh baseline consumer | 0 | 13 |
| New IDL edit | 1 generator | 12 |
| New XAML edit | 1 theme assembly | 12 |
| New task implementation edit | Task + Base + Dialogs + Themes.Simple | 9 |
| Each edited version, after producer publication | 0 | 13 |

All 254 baseline reference/runtime/generated artifacts match producer bytes.
Each edited variant also produced identical artifacts when independently executed
in both containers, and matches its subsequently recovered HTTP-cache artifacts.
The tool implementation edit leaves all 12 configured reference DLLs unchanged,
yet invalidates the task implementation's actual declared consumers. The IDL edit
changes the generated enum value to 42. The XAML edit changes the constructed
theme's style count from one to two; recovered runtime outputs retain that behavior.

Three fresh-output-base baseline recoveries took **8.96, 9.87 and 9.28 seconds**,
median **9.28 seconds**, with no compilation/generation. Each complete baseline
build reports 98 remote hits including package extractions. Edited-version
recoveries took 8.41–9.29 seconds. Initial publication took 49.26 seconds,
including cold Bazel startup, generation, compilation and uploads; source transfer
was also occurring on the host during that seeding run, so it is not a clean
compile-performance comparison.

For context, the preceding theme-only raw MSBuild clean-output build took 9.02 s
and the Bazel cold build 37.02 s. Those are single observations after package
restore, not paired medians against these remote cases; the remote suite also
includes the IDL action. No cross-machine, WAN or different-SDK equivalence is
claimed. [Compact evidence](avalonia-http-cache-evidence.json),
[locked package inventory](avalonia-xaml-package-lock.json).

## Reproduction

1. Prepare/build the theme graph with the prior setup helper. Run
   `avalonia/remote_setup.py <workspace> <pinned-Avalonia-checkout>` to add the IDL
   control and capture original source text for reversible edits.
2. Start the SHA-256 verified service described by scripts/bazel-remote.json with
   a fresh cache directory and a bridge-reachable HTTP endpoint.
3. Run `avalonia/remote_case.py <workspace> <fresh-base> <report.json> baseline
   --cache <URL> --upload` in the producer.
4. Copy declared sources/archives and identical tool binaries to different paths
   in a fresh container. Change the local rules override in MODULE.bazel. Supply
   the same qualified SDK and Bazel, plus a repository cache; do not copy action
   caches, bazel-* links or compiled project outputs.
5. Run remote_case.py there with `--expect-hits` and without `--upload`.
6. Run its `idl`, `xaml` and `tool` controls using fresh output bases. Publish each
   matching edit in the producer, then stop that container and recover each edit
   with fresh consumer bases and `--expect-hits`.
7. Execute Inspect.dll from the prior verification helper against downloaded
   runtime directories. Save its JSON as recovery-<case>-runtime.json.
8. Save seed.json, seed-<case>.json, consumer reports and cache-status.json together;
   run summarize_remote.py to validate byte equality and produce compact evidence.

The scripts are test scaffolding. All package/task behavior remains in the actual
upstream implementations; no package-specific core runner logic was introduced.
