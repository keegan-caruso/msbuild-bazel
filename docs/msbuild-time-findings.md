# MSBuild time-input diagnostics

This first slice reports potential time dependencies in MSBuild XML. It does not
ban time APIs in application source, evaluate conditions, change upstream build
semantics, or authorize preparation/action reuse. Production reuse stays disabled.

## Commands

```sh
python3 tools/check_msbuild_time.py path/to/Project.csproj --output /tmp/time-report.json
python3 -m unittest discover -s tests/msbuild_time -v
python3 tools/probe_msbuild_time.py --output /tmp/new-msbuild-time-evidence
```

The checker reports wall-clock property functions (`DateTime`/`DateTimeOffset`),
elapsed-clock property functions (`Environment.TickCount` and
`Stopwatch.GetTimestamp`), file/directory timestamp functions, and item timestamp
metadata (`ModifiedTime`, `CreatedTime`, `AccessedTime`). Each finding includes
file, element-start line, XML field, condition context, evaluation/target phase,
and target name. A finding means a potential dependency, not proof the expression
executed or affected an artifact. Explicit properties such as `OfficialBuildId`
are not clock reads.

The checker follows literal imports and `MSBuildThisFileDirectory` paths, including
imports with conditions it does not evaluate. Import edges retain their own
conditions separately from conditions inside the imported file. It deduplicates
cycles, handles XML namespaces/entities and one layer of MSBuild percent escapes,
ignores XML comments, and rejects DTDs and non-project entry files. It does not
follow Compile items or analyze C#/VB/F# source.

Dynamic/wildcard/SDK imports, absent literal imports, Exec and UsingTask produce
explicit coverage gaps. Supply known import files as additional entry arguments
to inspect them; this does not prove the evaluated closure is complete. Implicit
Directory.Build imports, indirect property functions, inline/precompiled task
code, external processes, and implicit MSBuild timestamp-based incremental
decisions are outside this check. Absence of findings never establishes eligibility.
Exit 0 means inspection completed, even with findings or coverage gaps; exit 2
means an input/read/XML error. JSON always says `eligibility: not-established`.

## Measured MSBuild probe

On native macOS ARM64 with SDK 10.0.400, the probe passed five cases at
`/private/tmp/msbuild-time-evidence-2/report.json`, using
`bash /private/tmp/run-sdk-latest python3 tools/probe_msbuild_time.py --output /private/tmp/msbuild-time-evidence-2`.
Twelve diagnostic tests also pass. No NuGet restore, C# compilation, Bazel action,
GitHub CI or cache recovery was run for this slice.

The authored SDK-free fixture approximates Azure's declared-build-ID/date-fallback
version expression; it is not an Azure SDK build or its complete version policy.
It imports Version.props and writes a version artifact in an ordinary MSBuild
target. A Compile item points to application code containing DateTime.Now; the
checker never scans that application code.

| Case | Observed result |
| --- | --- |
| Fixed build ID `20260907.1` | Version and artifact are `1.2.3-alpha.20260907.1` |
| Fresh workspace, same ID and staged timestamps | Same properties, artifact and experimental input fingerprint |
| Changed ID `20260908.2` | Fingerprint, version and artifact change |
| Same contents and ID, changed file timestamps | Fingerprint and version artifact stay equal; target-observed ModifiedTime changes |
| No explicit ID | Date fallback executes; checker retains the potential clock finding |

The experimental fingerprint covers fixture text, explicit properties and SDK
version only. It is deliberately not a production action identity. The timestamp
negative control shows why matching content fingerprints are insufficient to
establish eligibility. Fixed timestamps here are test setup, not a production
staging policy. The first probe attempt put the item transform in an evaluation
property; MSBuild returned the literal expression. Moving it into a target makes
the timestamp read observable. No clock changes or sleeps were used to simulate
a different day; date rollover and full build/cache invalidation remain unproven.

## Lessons from other build systems

Background primary-source research supports execution-role boundaries and explicit
inputs, rather than a blanket ban on time APIs:

- [Bazel workspace status](https://bazel.build/docs/user-manual#workspace-status):
  stable status changes invalidate consuming actions. Volatile values such as
  BUILD_TIMESTAMP do not independently invalidate them. This deliberately permits
  stale timestamp metadata on a cache hit; it is not a policy to silently impose
  on MSBuild assembly versioning.
- [Cargo build scripts](https://doc.rust-lang.org/cargo/reference/build-scripts.html):
  build scripts declare file/environment rerun inputs, separate from application
  execution. These declarations do not constrain arbitrary clock reads, and Cargo's
  mtime-based file detection is not our content-identity model.
- [Gradle configuration cache](https://docs.gradle.org/current/userguide/configuration_cache.html)
  and [external values](https://docs.gradle.org/current/userguide/configuration_cache_requirements.html#config_cache:requirements:external_processes):
  configuration inputs and task inputs are distinct; ValueSource can expose a
  computed value. A metadata step helps only if it captures all relevant behavior
  and its output remains unchanged.
- [Gradle caching problems](https://docs.gradle.org/current/userguide/common_caching_problems.html):
  separating expensive compilation from timestamp stamping can help. It changes
  the action boundary and requires semantic qualification here.
- [SOURCE_DATE_EPOCH](https://reproducible-builds.org/specs/source-date-epoch/):
  a declared timestamp can be reproducible when tools actually consume it. Merely
  setting the environment variable does not constrain arbitrary build code.

## Next gate

Use diagnostics to inventory actual evaluated project/import closures, then
qualify explicit build context consistently through discovery, execution and
recovery. Decide and enforce file-timestamp staging semantics separately. Require
fresh/cache-recovered parity, changed-input invalidation and negative controls
before enabling reuse; no clean-scan shortcut is valid.
