# R03 generated configured-node acceptance

## Selected inner framework: measured native macOS slice

The selected existing `net10.0` inner build of the authored Multi project passes
native macOS ARM64 execution and relocated local disk-cache recovery with SDK
10.0.100 and Bazel 8.4.2. Multi retains
`TargetFrameworks=net10.0;netstandard2.1`; its net10.0 inner build is now an
executable and the netstandard2.1 inner build remains a library. Frameworks are
not removed or retargeted. This extends the
[ordinary configured-node baseline](configured-node-findings.md).

With the pinned Nix tool overrides, ran:

```sh
python3 -m unittest discover -s tests/configured_execution -k selected_inner -v
```

One test passed in 24.191 seconds on 2026-09-07 UTC. Evidence remains at
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/configured-execution-i6ikz1vk/probe`.
The native test ran outside Codex's enclosing sandbox without disabling Bazel's
native sandbox. Its ordinary MSBuild baseline was built in a separate copied
workspace, then removed.

| Case | Observed result |
| --- | --- |
| Cold | One `darwin-sandbox` Multi action; exact project compile marker once; output `multi`, matching ordinary MSBuild. Preparation workspace was removed first. |
| Unchanged | No new configured action; executable still prints `multi`. |
| Relocated | Producer preparation/generated workspace and original Bazel output base removed. Independently restored source prepared at a new path, then removed. One disk-cache hit, no compilation; recovered executable prints `multi`. |
| Outer rejection | Export without selecting TargetFramework rejects `unsupported-configuration` and publishes no manifest. |

All consumer bundle files and executable bits are retained and independently
hashed by the test. The relocated bundle digest equals cold output. Real actions
must report native sandbox execution, `remotable=false` and
`remoteCacheable=false`. The test checks exact raw compile markers as well as the
runner's basename diagnostic field; no dependency compilation can be hidden by
that shorter field.

The ordinary three-test suite also passed in 10.149 seconds after the executable
fixture extension, including the unchanged full outer-framework ordinary baseline.
No Linux acceptance is claimed for this new slice; CI acquisition/billing
availability is separate from a passing local run.

## Configured direct edges: measured native macOS slice

After integrating the configured implementation and replay diagnostic fix, ran:

```sh
python3 -m unittest discover -s tests/configured_execution -v
```

Both tests passed in 86.489 seconds on native macOS ARM64 at stable commit
`7e1e529` on 2026-09-07 UTC. The configured evidence directory is
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/configured-execution-yseelx4d/probe`;
the repeated selected-inner evidence is the sibling
`configured-execution-p5wfbnau/probe`. Tool versions are unchanged from above.

The probe consumes the normal preparation API and exported configured identities
and output declarations. Shared red and blue have distinct IDs and evaluated
artifact/restore paths; their Common dependency has one ID and no Flavor global.

| Case | Measured action and runtime evidence |
| --- | --- |
| Cold | Six real native sandbox actions: Common, Shared/red, Shared/blue, Left, Right, App. Each action compiles only its requested project. App prints `red:common\|blue:common`, matching ordinary isolated MSBuild. |
| Unchanged | No executed actions; output unchanged. |
| Right edge changes blue to red | Re-exported graph has five nodes. Only Right and App execute. Both branches now reference the same Shared/red node and App prints `red:common\|red:common`. Actual Bazel dependency analysis equals the new manifest. |
| Relocated original graph | Original producer/preparation and output base removed, independent source restored/prepared at a new path and removed before execution. Six disk-cache hits, zero compilations, original output restored. All six consumer bundle digests match cold bytes/executable bits. |
| Unsupported outer graph | Export returns 2 with `unsupported-configuration`, no manifest. |
| Default transitive configured graph | Export returns 2 with `unsupported-configured-transitive`, no manifest. The ordinary nonisolated success and isolation failure remain recorded separately. |

For full bundle-byte verification the probe explicitly requests every configured
node target as well as `:all`. An all-hit entry action can otherwise leave its
dependency output trees unmaterialized locally; missing unrequested trees are not
corruption. The test still executes the recovered App directly after recovery.
Reports, raw execution JSON, per-action logs and every compared bundle file are
retained beneath the evidence directory.

Keep the checkout revision and tool sources stable throughout these action-set
experiments. Preparation rebuilds adapter tools, and .NET incorporates the Git
revision in their informational version. A preliminary run crossed a commit and
correctly rebuilt more nodes after the tool bytes changed; its action-set failure
is not used as passing evidence. The complete passing rerun above used one stable
revision.

No Linux run has qualified these new R03 cases. GitHub CI billing/spending-limit
failures before job startup provide no execution evidence.

The selected-inner result is a root project, not proof of downstream framework
selection. An attempted InnerApp -> Multi ordinary graph still introduced an
outer Multi and both inner nodes despite the root TargetFramework selection and
an explicit edge AdditionalProperties selection. It failed for un-restored
netstandard2.1 assets; this downstream shape remains open and is not used as
passing adapter evidence. The fixture in this record selects Multi itself.

Full outer graph execution, default transitive configured semantics, solution/SDK
extensions, arbitrary configurations, Serilog, cross-platform reuse and remote
support remain outside the selected-inner measured boundary.

The integrated selected-inner implementation also passed all 12 existing
handoff/discovery tests at `eebbc12` on native macOS (126.310 seconds). This
regression run predates the broader configured-path implementation.

At integrated `737e29f`, all 13 full package-cache tests passed in 255.320 seconds
and all seven PrivateAssets/restore-semantic tests passed in 146.097 seconds on
native macOS. The same production changes passed 18 graph-execution tests, 14
exporter tests and the explicit binary-package e2e regression. The exporter suite
needed a serial retry after another build rewrote a runtimeconfig file during a
read; the retry passed without source changes. These are correctness results,
not controlled performance measurements.

Review also corrected an empty-directory prefix check that rejected projects at
the workspace root. The existing root-project native probe passed after that fix,
with preparation deleted and ordinary/generated output equal. Evidence:
`/private/tmp/msbuild-r03-root-review/report.json`.
