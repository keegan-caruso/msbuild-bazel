# Changed builds with an HTTP project cache

The subsequent [API/runtime follow-up](native-api-runtime.md) implements the
boundary recommended by this baseline and records fresh changed-build results.

The priority is reuse across revisions on fresh consumers. Warm local MSBuild
incrementality is a separate comparison, recorded in the [overhead follow-up](native-workflow-optimization.md).

## Protocol

`tests/preparation_reuse/measure_changed_remote.py` uses the current integrated
native workflow and the existing explicit HTTP project-cache broker. One producer
builds and uploads an immutable catalog and sealed project bundles. Its source,
preparation, project cache and Bazel state are deleted before any consumer runs.
Each consumer has a new source path, preparation state, controller instance and
Bazel output base, with no local compiler outputs or project seeds. It receives
only the catalog digest; catalog and artifact bytes come through HTTP.

The cache is an in-memory loopback service on the same macOS ARM64/Nix host. The
100-project owned fan graph uses explicit net10 configured nodes. Three repetitions
alternate raw/native order. Every consumer starts from the same producer snapshot,
so an earlier changed consumer cannot warm a later one. The service adds 10ms per
request; there is no bandwidth cap, WAN jitter, TLS or independent-machine claim.
This is native project CAS around a sandboxed Bazel action, not a Bazel ActionResult
cache or remote execution. The normal CLI's remote configuration is not expanded.

Two source-only edits preserve public signatures:

- **Leaf:** change N0098, which has the application as its only consumer.
- **Shared:** change N0000, a dependency of the entire graph.

Native time includes fresh SDK/tool verification, full discovery/preparation,
catalog download, artifact download/verification, staging, fresh Bazel startup,
compilation, local publication, remote upload and new-catalog publication. Raw
MSBuild starts from restored inputs without compiler outputs. SDK acquisition,
Restore, executable/hash oracles and Bazel shutdown are outside both timers.

Correctness checks require the exact cache-miss project set, actual C# compiler
counts, native sandbox execution, remote hit counts, runtime-byte equality with
raw, and the independent executable result. All 100 reference assemblies are also
compared across leaf/shared cases to establish that these are implementation-only
changes. This reference comparison is a post-run oracle outside both timers.

Reproduce inside the pinned Nix shell:

```sh
python3 tests/preparation_reuse/measure_changed_remote.py \
  --output /private/tmp/changed-remote --count 100 --repetitions 3 --delay-ms 10
```

## Why the shared edit matters

`NativeCachePlugin.DependencyIdentity` uses `artifacts.json` under the evaluated
package policy. A dependency implementation or copied runtime file therefore
changes a consumer's compilation key, even when the reference assembly is equal.
This invalidation repeats through the graph. Downloaded bundles may be intact
and verified against their snapshot hashes yet unusable for the changed
dependency key; successful downloads must not be counted as compilation hits.

The earlier owned package-free policy already uses reference-assembly hashes and
separate runtime composition. Extending that model to the evaluated/package
workflow is the next change: compile against API/compile-affecting identities,
then compose runtime outputs from current producers. Merely changing the hash
would leave stale copied DLLs inside cached consumer bundles. Package/runtime
metadata, analyzers and API changes need explicit controls before enabling it.

## Measured results

All six paired 100-project cases pass (three repetitions per edit), including
exact rebuild sets, runtime bytes and behavior. The post-run reference audit
confirms all 100 reference assemblies are identical across all six cases. The
10-project pilot also passes both edits. Medians include transport/publication.

| Edit | Compiled | Compilation hits | Native seconds | Raw clean seconds | Download bytes | Upload bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| leaf | 2 | 98 | 22.156 | 26.094 | 5,699,969 | 901,417 |
| shared | 100 | 0 | 47.061 | 25.969 | 5,748,130 | 5,759,580 |

The leaf case is **15.1% faster** than clean raw MSBuild. The shared body edit
is **81.2% slower**, despite unchanged API reference bytes. Both consumers fetch
100 blobs including the catalog; the leaf run makes 103 HTTP requests total,
whereas the shared run makes 201 because every compiled bundle is republished.
The 99 downloaded project bundles yield 98 compilation hits for the leaf and
zero for the shared edit. This distinguishes transport hits from useful reuse.

For the leaf case, median fresh preparation is **12.126 s**, the Bazel command
including server startup is **7.439 s**, and catalog/bundle download and verification
is **0.207 s** (inside staging). Final remote publication is **0.266 s**.
Thus the next priorities are correct API-based compilation reuse and reusable
discovery/preparation for fresh consumers. Faster transfers alone cannot remove
the measured invalidation and preparation costs.

These measurements do not change the production cache policy. A future API/runtime
split must retain the changed executable oracle, raw runtime-byte equality,
failed-build non-publication, corrupt-bundle rejection, API-edit invalidation and
package/runtime metadata controls. No GitHub CI or production cache was used.
