# R05 Spectre selected-framework prerequisite

This slice extends configured graph execution from `net10.0` to the selected
`net10.0` and `netstandard2.0` pair. It retains the normal SDK reference negotiation;
upstream declarations are not retargeted. Other frameworks, unselected outer
builds, RID builds and unsupported global properties remain rejected.

The exporter and preparation guards accept the selected framework identity, and
fallback output paths use that identity. Generated selection imports now condition
each project on its own framework. Replay capture records the evaluated producer
framework instead of always writing `net10.0`; consumption still checks it against
the evaluated request, along with configured properties and payload seals.

## Focused evidence

On macOS ARM64 with the pinned Nix SDK 10.0.400 and Bazel 8.4.2,
`python3 -m unittest discover -s tests/generator_roles -v` runs the native
regression matrix. The project-analyzer and package-analyzer combinations each
passed their ten cases, including producer-free recovery and fresh consumer
compilation.
The fifteen-case role variant also passed, for 35 native cases total. The full
suite passed all ten unittest methods, including ordinary controls and stale
restore/reference-role rejection. `bash scripts/check-dotnet.sh` passed owned
build, formatter and five enforcement controls before the final unit-test
extensions. Final focused checks also passed:

- `python3 -m unittest discover -s tests/graph -p test_selected_framework.py -v`:
  all three tests passed. This includes netstandard identity/output discovery,
  existing multi-target SDK negotiation and unsupported-framework rejection.
- `bash scripts/dotnet.sh run --project tests/ActionRunner.Tests -c Release`:
  contract/process tests passed, including mixed selected-framework imports.
- Formatter verification for the updated ActionRunner unit-test project passed.
- `git diff --check` passed.

The selected-framework discovery test isolates negotiation by disabling implicit
framework package references in its copied fixture; it does not compile that
fixture or qualify the NETStandard.Library payload. The runner unit check covers
mixed-framework selection imports and rejection of an unsupported framework.

## Integration boundary

Actual Spectre generator execution requires the separate NETStandard.Library and
Roslyn package policies, central version resolution and build-input work. Full
Spectre build, mutation and producer-free relocated-cache acceptance belong to the
integration harness. Passing existing net10.0 regressions is not evidence that
this real-project gate has passed. No Linux or remote-cache qualification is
claimed here.

## Explicit parent framework correction

The first integrated Spectre export exposed `NETSDK1005`: an explicit net10.0
entry framework flowed into the single-target netstandard2.0 generator. Ordinary
SDK negotiation puts `TargetFramework` in `UndefineProperties` for single-target
children, while static graph construction consumes `GlobalPropertiesToRemove`.
The exporter now merges the SDK removal metadata into the graph edge, retaining
any existing removal list. It still copies selected-framework metadata for
multi-target children.

The discovery regression now gives App an explicit net10.0 global property and a
direct reference to the declared netstandard2.0 child. Before this correction it
failed with the same `NETSDK1005`; afterward all three selected-framework tests
passed. Assertions require the parent global to remain net10.0, the child to have
no inherited framework global, its evaluated framework/output to remain
netstandard2.0, and SDK-selected multi-target behavior to remain intact. The
fixture still isolates discovery from framework-package acquisition as described
above. Exporter build and formatter verification also passed; real Spectre
execution remains the integrated acceptance gate.

## Matching implicit framework globals in actions

The next integrated cold run successfully compiled the netstandard2.0 generator,
then rejected its replay in Ansi. The action's recorded graph showed an inherited
net10.0 global on the generator; export had correctly omitted that global. The
prepared selection contract now carries `remove_framework_global` for nodes whose
exported globals omit TargetFramework. The runner appends TargetFramework to the
removal list of existing references to those nodes before static graph expansion.
This neither adds references nor weakens replay's exact property comparison.

The new native `test_explicit_framework.py` gives the consumer an explicit net10.0
global while its four producers have implicit framework declarations. Its cold
sandbox build passed with one compilation per action and all dependency replay
hits; exported producer globals remain implicit. This is a package-free net10.0
regression of the property mismatch, separate from actual Spectre acceptance.
Five preparation-selection tests and the ActionRunner contract/process suite
also passed, including rejection of attempts to collapse explicit and implicit
identities for the same project path. Formatter verification and diff checks
passed.
