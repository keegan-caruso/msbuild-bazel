# Graph-only cutover

Sync now emits graph contracts without a mode switch. The per-project compiler,
worker, generator, rules/providers and their fixtures are removed. The quickstart,
source-SDK consumer declarations, analysis tests and benchmark adapters use graphs.
ArtifactTools retains package/layout/launch utilities. Tool bindings consume complete
layouts; `msbuild_graph_output` exports only contract-owned files.

## Validation

Checks ran in the qualified Ubuntu ARM64 container: SDK 10.0.400, four CPUs,
8 GiB RAM. Reports stayed outside Git. No GitHub CI was dispatched.

| Command | Observed result |
| --- | --- |
| `bash scripts/check.sh` | Shell, pins, tooling and Starlark checks passed |
| `bash scripts/check-dotnet.sh` | Four tools built/formatted without warnings; 30 unit tests passed |
| `USE_BAZEL_VERSION=8.8.0 bash scripts/check-analysis.sh` (also 9.2.0) | 15 analysis tests and aquery execution requirements passed on each version |
| `python3 -m unittest discover -s tests/sdk_repository -v` | 15 SDK/runtime repository tests passed |
| `python3 -m unittest discover -s tests/source_sdk -v` | 17 source inventory/component tests passed |
| `python3 -m unittest discover -s tests/ci -v` (also bootstrap and benchmarks) | 5 CI, 13 bootstrap and 4 benchmark unit tests passed |

All slices in `tests/graph_build/acceptance.py` passed: qualification, replay,
reviewed dependency boundaries, source groups, output ownership, signing, package
SDKs, quickstart run/test, managed/native tools and real MTP/VSTest protocols.
They ran individually; the initial controller stopped on a stale quickstart
contract, which was regenerated and then passed.

Additional controls:

```sh
python3 tests/graph_build/linux_worker.py --bazel-version 8.8.0  # also 9.2.0
python3 tests/graph_build/tools.py --task-host --graph-worker
python3 tests/graph_build/prepared_restore_sync.py
python3 tests/graph_build/linux_prepared_restore.py --generated --worker
python3 tests/graph_build/remote.py
python3 tests/source_sdk/package_handoff.py /tmp/fresh-package-handoff
```

Both worker baselines passed sandboxed Build/Publish parity, request reuse,
property invalidation and failure recovery. Managed task-host bindings preserved
package/data dependencies and invalidated on implementation/data edits without
resync. Prepared Restore reused its action on a body edit (two project hits),
refreshed on a props edit (zero hits), and verified the executable result.
The Linux Restore control requires `RULES_MSBUILD_PROJECT_CACHE_URL`.

Generated package handoff passed body-edit refresh, identity rejection, missing
output rejection and source-archive rejection. HTTP tests passed authentication,
transient retries, parallel transfers, payload deduplication and missing/corrupt/
interrupted artifact recovery.

## Limits

This qualifies the cutover's small fixtures on Linux ARM64. The full source-SDK,
NoTargets and NativeAOT consumers need graph-only requalification. The 481-node
runtime build and [performance scorecard](performance.md) are historical results,
not fresh measurements of this revision. No Linux x86-64, macOS-worker or RBE
qualification was added. See [current support](implementation-plan.md).
