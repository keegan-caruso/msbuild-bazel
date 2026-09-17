# Portable native cache inside a Bazel action

## Architecture

`bazel/native_cache.bzl` runs one native MSBuild graph build in `darwin-sandbox`.
An explicit snapshot broker (`tools/portable_cache.py`) obtains project bundles
before the action and declares every seed file as a Bazel input. The action has
no remote-cache client configured and external networking is blocked. It exports the entry
runtime and the selected project bundles as declared outputs. The broker validates
and uploads bundles only after a successful action. It uses bounded parallel
transfers and tolerates service failures by falling back to compilation and
reporting upload failures.

This is a simpler initial boundary than a persistent worker or an action-time
network broker. It retains Bazel's native execution strategy and makes seed
contents visible to Bazel's action identity. There is no hidden on-disk worker
state. The cost is that a changed seed snapshot changes the outer action key even
when sources are unchanged. Repeated identical snapshots can recover the whole
Bazel action, including its project bundles, without executing MSBuild.

The snapshot catalog is explicit immutable input to the broker; it is not an
implicit mutable "latest" lookup. It records project identity, own input hash,
toolchain hash, project key and content digest. The broker selects candidates
matching current own inputs/toolchain; the plugin independently checks the full
key, including dependency API hashes. Missing candidates are normal misses.
After success the runner discards unused seed versions so each published snapshot
contains only this graph's selected bundles. Selecting a seed never permits a
cached application to retain an old dependency implementation: runtime composition
still uses current producer implementations.

## Portable identity

The native-cache runner is now also an executable. Its DLL serves as both the
MSBuild plugin and the sandbox runner. Controller and runner installation paths
are identified by verified file content and role. Platform/architecture, the
pinned SDK snapshot, explicit external SDK imports, controller bytes, runner bytes
and environment policy participate in tool identity.

The runner clears the compiler process environment and creates a controlled one.
HOME, CLI home, temporary directories and NuGet locations are fresh request-local
roles; they are not inherited from the user's shell. The generated targets path
is normalized as a verified tool role in global properties. Compiler path mapping
normalizes the workspace while authored source bytes remain exact key inputs.
The runner refuses a pre-existing nonempty output directory.

The Build-only restore handoff includes `project.assets.json` and generated
`.nuget.g.props`/`.nuget.g.targets`. It excludes restore diagnostics/receipts such
as `project.nuget.cache`, whose `dgSpecHash` differed across independently restored
roots in the first test. Restore itself remains a separate setup operation. This
is not a general policy for arbitrary targets or packages.

The relocation test uses independently restored sources, different controller
and runner directories, different CLI homes, staging directories and output
bases, with no consumer compilation state. The two controllers use the same
pinned Nix SDK on the same host. SDK relocation, different hosts and general
NuGet/package workloads are not qualified by this test.

## Cache correctness and sandbox checks

The owned ten-project matrix checks cold compilation, portable recovery, inner
project hits, outer action recovery, body edits, API additions, corruption,
missing blobs, changed tool identity, empty seeds, native-cache service outage,
recovery and a failed compilation without project-cache publication. Every
successful build executes the independent application oracle. Cold/body results
are compared with raw MSBuild runtime DLLs byte-for-byte; recovery is compared
with the producer. Fault cases use an explicit test nonce to avoid an outer
Bazel cache hit hiding the inner behavior being tested.

The macOS sandbox permits reads through known absolute host paths. The initial
write probe under `/private/tmp` was also allowed; temporary directories are not
a useful outside-write boundary on this setup. The final write probe uses an
owned sentinel outside temporary directories. A separate action-side network
probe demonstrates the documented localhost exception and separately checks
external-network denial. Normal actions are checked for zero project-cache
requests during Bazel execution. The report records these outcomes; native sandbox execution does not establish full filesystem
hermeticity or complete host closure. This distinction agrees with
[Bazel's sandbox documentation](https://bazel.build/docs/sandboxing) and the
[`block-network` localhost exception](https://bazel.build/reference/be/common-definitions#common.tags).
Both final ten-project runs observed absolute reads and localhost access allowed,
outside-temporary-directory writes and external network denied.

## Measurement protocol

All sources are the owned package-free net10.0 Release fan fixture on macOS ARM64,
SDK 10.0.400 and Bazel 8.4.2, with two compiler slots. HTTP storage is loopback,
not a production cache or a WAN. SDK snapshot cost is charged to the first cold
candidate; tool compilation and restores are separately recorded setup.

Candidate time includes source qualification, capture, tool identity, seed
selection/download/validation/staging, Bazel, SDK compilation/runtime composition,
and broker publication. Application oracles, DLL comparisons and Bazel shutdown
are outside the timer. Execution logging remains enabled for hit provenance.

The fresh-consumer mode uses a separate Bazel output base and generated workspace
for every invocation. The retained mode keeps one Bazel server/output base per
controller and regenerates declared inputs at the same workspace path. It still
uses a new native sandbox for every executed action. This separates remote
recovery evidence from the cost developers see with a retained Bazel server.

An unchanged request with newly populated seeds can cause one transition action;
thereafter an unchanged explicit snapshot can hit the outer cache. Seed snapshot
identity and publication cost are part of this initial design, not free services.

## Measured results

All four final matrices passed: ten projects with the full fault/sandbox matrix
in both fresh and retained modes, and 100 projects with three distinct body edits
in each mode. Times below include the broker work described above. Cold and first
seeded recovery are single samples; body edits are medians of three; steady
unchanged recovery is the median of two samples.

| 100-project case | Fresh Bazel consumer | Retained Bazel server | Paired raw MSBuild, retained run |
| --- | ---: | ---: | ---: |
| Cold build | 34.141 s | 34.186 s | 25.718 s |
| First seeded recovery, 100 inner hits | 6.517 s | 6.777 s | Not measured |
| Stable unchanged snapshot, outer hit | 4.886 s | 1.361 s | Not measured |
| Body edit, 1 compile and 99 inner hits | 6.970 s | 3.289 s | 3.326 s |

The retained-server body-edit path is approximately at raw MSBuild parity in this
fixture (1.1% lower median, too small to claim a meaningful speed advantage).
Its individual samples were 3.457, 3.274 and 3.289 seconds, compared with raw
3.326, 3.307 and 3.338 seconds. Runtime DLL bytes matched in every paired build.
The fresh-server body-edit path remains about 2.1 times its paired raw median
of 3.304 seconds. Keeping the Bazel server is consequential.

Cold builds remain 32.9% slower in the retained-mode run, an 8.468-second gap.
The retained body-edit median consists of about 0.480 seconds preparation,
2.650 seconds Bazel/build, and 0.157 seconds publication/remaining controller work
(component medians, not an exact additive decomposition of the total median).
Stable outer hits still repeat snapshot download/validation and publication.
The next optimization targets are avoiding redundant transfers for an unchanged
explicit snapshot and profiling the cold Bazel action/output overhead. These
measurements do not establish cold parity or performance for larger real projects.

Portable direct recovery outside Bazel took 1.695 seconds in the retained-mode
matrix, with all 100 projects reused after relocating the source, restored state,
controller, runner and CLI home. That result isolates the inner cache mechanism;
it is not the end-to-end Bazel time.

Validation also passed the existing local native-cache matrix (18 samples),
HTTP native-cache matrix (19 samples), 17 native-cache unit tests, warning-free
.NET build/style verification and Starlark formatting/lint (11 files).

## Reproduction and limits

Inside the pinned Nix shell, use fresh short output paths. The sentinel root must
be an owned writable directory outside temporary directories:

```sh
python3 -m unittest discover -s tests/native_cache -v
python3 tools/probe_portable_cache.py --output /private/tmp/native-sandbox-10 --sandbox-probe-root /absolute/owned/non-temporary/probes
python3 tools/probe_portable_cache.py --retained --output /private/tmp/native-retained-10 --sandbox-probe-root /absolute/owned/non-temporary/probes
python3 tools/probe_portable_cache.py --nodes 100 --repetitions 3 --no-extended --output /private/tmp/native-fresh-100
python3 tools/probe_portable_cache.py --retained --nodes 100 --repetitions 3 --no-extended --output /private/tmp/native-retained-100
```

The rule and controller are experimental and opt-in. Arbitrary SDK targets,
packages, tests, user generators, SDK relocation, cross-platform reuse, remote
execution, authenticated remote services and complete host closure remain outside
this slice. There is no new default build path and no CI was dispatched.
