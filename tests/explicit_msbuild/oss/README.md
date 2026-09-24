# Pinned open-source build comparisons

Test scaffolding for Serilog, Spectre.Console and Polly, not a production project
importer. The selected versions, framework slices, edits and symmetric source
patches are in `projects.json`. The scripts require Python 3.10+, the repository's
.NET 10.0.400 SDK and Bazel 9.2.0, and the qualified Ubuntu 22.04 ARM64 worker
platform with bubblewrap. Run on the container's native filesystem, not a Mac
bind mount. The recorded machine has four CPUs and 8 GiB RAM.

Inside that environment, with this repository at `/workspace`:

```sh
export RULES_MSBUILD_DOTNET_ROOT=/opt/rules_msbuild-toolchain/.tools/dotnet
export RULES_MSBUILD_BAZEL=/tmp/bazel
export RULES_MSBUILD_REPOSITORY_CACHE=/tmp/repository-cache
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
cd /workspace
bash scripts/dotnet.sh build tools/ExplicitBuild -c Release -warnaserror
```

Obtain exactly the commits in `projects.json`, in `/sources/serilog`,
`/sources/spectre` and `/sources/polly`. Verify the Bazel binary against the ARM64
SHA-256 in `scripts/toolchains.json`; the environment overrides let an older
prebuilt image use the current pin. The source folders must be Git checkouts;
setup verifies HEAD and copies sources without `.git` or build outputs.
Use clean checkouts: uncommitted source modifications are not a benchmark input.

```sh
python3 tests/explicit_msbuild/oss/setup.py /sources /work
for project in serilog spectre polly; do
  python3 tests/explicit_msbuild/oss/prepare.py /work/$project /workspace
  python3 tests/explicit_msbuild/oss/benchmark.py /work/$project --repeats 3
done
```

`setup.py` needs network access to restore packages to `/tmp/nuget`. It selects
one framework per multi-targeted project, pins the SDK in each disposable copy,
restores packages, installs required .NET 8 reference packs into the declared
SDK, evaluates the selected graph, and checks the raw Release build. Single-target
source-generator projects keep their framework. The temporary solution includes
all graph nodes so MSBuild does not default unlisted dependencies to Debug.
Run setup for **all projects before measuring**; SDK pack changes alter tool inputs.

`prepare.py` writes explicit BUILD inputs from that inventory, with archive
hashes and lock-only restore dependencies. No discovery, graph export, package
acquisition or BUILD generation runs inside a timed command. Compare
`package-lock.json` with the recorded evidence when reproducing these results.
If resolution changes, that is a different benchmark configuration.

`benchmark.py` alternates raw/Bazel ordering across three repetitions and reports
wall time for cold outputs/processes, a no-op, and a method-body edit. Cold runs
include restore and process startup, but use warm package/repository/OS caches.
Bazel uses four persistent workers and has no disk or remote action cache for
those cases. Raw uses `dotnet build -m:4`; both use portable PDBs and reference
assemblies. An edit must change the runtime DLL and preserve reference DLLs.
Raw versus Bazel reference DLL hashes are recorded separately.

The final case seeds a loopback HTTP cache, shuts down Bazel, deletes the producer
checkout/output base, and recovers into a relocated checkout and fresh output
base/user root. All runtime and reference bytes must match; every assembly action
must hit the cache. Full remote output downloads are requested. This one sample
includes fresh Bazel startup/repository setup; it is a correctness control and
local recovery measurement, not a WAN throughput result. The cache is not remote
execution. OS/package caches and the declared SDK remain available.

Results and diagnostic logs/profiles are under `/work/<project>/evidence`.
The harness intentionally deletes its generated producer checkout during cache
recovery, preserves raw sources, and restores the edited source after each run.
Use fresh output directories for another experiment. These commands build the
selected library graphs; they do not run upstream test suites, packing, publishing
or all target frameworks. See `docs/oss-build-benchmarks.md` for results and limits.
