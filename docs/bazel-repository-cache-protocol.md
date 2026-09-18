# Bazel repository-cache measurement protocol

Declared before final timing collection. Preflight measurements are excluded.

- Start from the cache-hit-overhead candidate, retaining shared final scans and
  the separately provisioned Bazel installation in every comparison.
- Pin the native workspace MODULE lockfile from the verified Bazel 8.4.2 baseline.
  Require `--lockfile_mode=error`; never silently refresh resolution while building.
- Measure lockfile-only, with isolated repository downloads: unchanged diamond
  and Serilog, three repetitions each.
- Then measure lockfile plus a shared repository-download cache: unchanged and
  body edits, three repetitions per workload/case. Start the shared cache empty;
  let the producer provision it and record producer timing separately.
- Keep every consumer's source, preparation, output base, server and action cache
  fresh. Delete the producer's source and build state before consumer execution.
  Shared repository downloads and installed Bazel are provisioned tool inputs,
  not project outputs. Native artifact recovery still uses the real pinned CAS.
- Preserve raw MSBuild's incremental state; alternate raw/adapter execution order
  by repetition. Require exact DLL/PDB equality, actual application/approval-test
  execution and expected compiler counts (unchanged 0, body 1).
- Use the prior wall-time protocol: exclude initial Restore/tool acquisition,
  include CLI startup, identity, preparation, transfers, Bazel/actions/tests,
  exit validation and publication. No concurrent build/test work during timings.
- Inspect existing Bazel profiles. A trace event named download may be a local
  cache lookup: do not count it as an external HTTP request.
- Separately deny external process networking while allowing local sockets and
  loopback, prove a public fetch is blocked, then require dependency resolution to succeed from the warm cache. Require fresh
  native recovery with Bazel repository-rule downloads disabled; an outer macOS sandbox
  cannot wrap native action sandbox creation.
  Missing/corrupt repository objects and outdated lock data must not be accepted;
  the lockfile must remain unchanged in error mode.
- Report medians, all samples, provenance and limits. Retain the raw-MSBuild
  diagnostic target (adapter <= 1.25 * raw + 0.250 s); do not relax it after results.
  This same-host experiment does not establish independent-worker acceptance.

Preflight established that Bazel 8.4.2 can fetch missing registry files despite
`--repository_disable_download`. The production option is named
`--bazel-disable-repository-downloads` and documented with that limitation; the
negative registry controls rely on the external-network-denying process policy.
