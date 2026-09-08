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
