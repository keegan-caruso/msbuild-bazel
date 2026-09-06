# Next six milestones

This roadmap follows the managed binary-package milestone merged in PR #2.
It extends the historical sequence in [spike-plan.md](spike-plan.md). Milestone 1
has passing acceptance evidence; later milestones require their own evidence
before completion can be claimed.

At every milestone, define interface contracts and executable acceptance tests
before implementation. Record failing tests first, then measured results and
limitations. Keep experiments independently runnable and retain existing controls.

## 1. Export configured project graphs

Status: acceptance implemented, with all 12 tests passing on Linux x86-64 CI;
see [graph export findings](graph-export-findings.md).

Build a local C# `ProjectGraph` exporter and custom MSBuild input/output targets.
Identify nodes by project path plus global properties, preserve direct dependency
edges, and declare source, import, restore, package and output boundaries.

Completion criteria:

- A four-project diamond exports correctly and deduplicates its shared dependency.
- Different global-property configurations remain distinct nodes.
- Equivalent restored checkouts at different paths produce identical normalized manifests.
- Unsupported configurations, missing inputs and path escapes fail explicitly.
- Export does not compile projects or imply automatic Bazel graph integration.

## 2. Execute exported graphs through Bazel

Status: the [first execution slice](graph-execution-contract.md) targets a
Release/net10.0 managed diamond. See [execution findings](graph-execution-findings.md)
for measured results and narrower support limits. This does not yet claim
execution of every configuration accepted by the exporter.

Generalize the two-project runner, dependency-result replay, artifact bundles and
Bazel rules to consume exported nodes, including multiple dependencies.

Completion criteria:

- Bazel executes the exported diamond graph with one action per configured project.
- Its shared dependency compiles once and is not rebuilt inside consumer actions.
- Dependency artifacts and result metadata reach every consumer correctly.
- Application behavior matches the ordinary MSBuild static-graph baseline.

## 3. Prove selective invalidation and cache recovery

Status: [contract and executable acceptance](graph-cache-contract.md) prepared.
The separate suite is intentionally red until its probe is implemented; no
generated-graph cache acceptance is claimed.

Extend existing two-project cache evidence to generated graphs. Exercise source,
shared configuration, package and graph-structure changes.

Completion criteria:

- Only actions affected under the declared dependency/input contract rebuild.
- Unchanged builds reuse results; shared changes invalidate dependent work.
- Graph changes regenerate the plan and update dependencies before Bazel analysis.
- Clean workspaces recover artifacts from the local disk cache.
- Relocated builds succeed without access to the producer workspace.
- Missing, corrupt and stale inputs remain explicit failures.

## 4. Validate a representative real project

Status: [pilot discovery and ordinary MSBuild baseline](real-project-pilot.md)
prepared. Adapter compatibility and comparative performance remain future work.

Select a .NET subtree with realistic dependencies and custom build behavior.
Inventory its requirements before widening the adapter's support boundary.

Completion criteria:

- Selected build outputs and observable behavior match the MSBuild baseline.
- Supported behavior has regression coverage; unsupported behavior is rejected clearly.
- Cold build, incremental build and cache-recovery performance are measured.
- Findings document compatibility gaps and the cost of adopting the adapter.

Multi-targeting, RID/native assets or specialized SDK support may move ahead of
later milestones if this pilot requires them. Each expansion needs its own
contracts and acceptance evidence.

## 5. Prove shared remote caching

Reuse Bazel artifacts across independent CI workers while execution remains local.
Make SDK, package, environment and platform identities explicit.

Completion criteria:

- A second independent worker gets cache hits without the producer's files or state.
- Relevant input changes invalidate entries.
- Incompatible environments cannot share entries.
- Recovered artifacts match the baseline and retain required metadata and permissions.

Begin with a defined compatible worker platform; this does not establish reuse
between operating systems or architectures. Remote caching follows local cache
correctness because it adds an independent consumer and shared artifact storage.

## 6. Prove remote execution

Run individual MSBuild actions on remote workers using declared inputs and a
provisioned toolchain. Resolve the remaining runtime and host dependency closure
before claiming this milestone complete.

Completion criteria:

- The representative project builds from empty worker state.
- Actions require no undeclared filesystem or network dependencies.
- Dependency handoff, output collection and cache identity work across remote actions.
- Outputs are equivalent to the baseline under the documented comparison contract.
- Missing toolchain/runtime inputs fail clearly rather than falling back to host state.

## Scope and risks

Milestones 1–4 establish local correctness and usefulness. Milestones 5–6 require
new evidence; existing sandbox and local-cache results do not prove either one.
Arbitrary .NET SDK/package compatibility, cross-platform artifact reuse and full
host closure remain unproven. Restore and tool acquisition stay outside build
actions unless a later explicit contract changes that boundary.

Use the [risk register](edge-cases-and-risks.md) when refining acceptance tests,
and the [spike plan](spike-plan.md) for links to measured findings.

The [scenario and coverage mapping](scenario-coverage.md) maps the proposed
project portfolio, generator variants and shared acceptance checks to these
milestones, with measured evidence kept separate from planned coverage.
