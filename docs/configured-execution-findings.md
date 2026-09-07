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

## Next configured slice and explicit boundaries

`tools/probe_configured_nodes.py --scope configured --output NEW_DIRECTORY` and
the separate `test_same_path_configurations_and_edge_convergence` acceptance
method define the next slice. They consume the normal preparation API and
exported identities/output declarations. They require six configured nodes,
Shared red/blue bundles with distinct IDs, Common convergence, Right's blue-to-red
edge mutation rebuilding only Right/App, actual Bazel dependency analysis, and
relocated byte-identical cache recovery. Default transitive references must fail
explicitly with `unsupported-configured-transitive` before manifest publication.
These assertions were prepared alongside production work; this record does not
yet claim they pass.

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
