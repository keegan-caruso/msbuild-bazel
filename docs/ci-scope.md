# Manual CI scope and cost

GitHub CI runs only on explicit user request. `linux.yml` consolidates the former
setup, graph-export and graph-execution workflows. Its default `quick` selection
uses one Ubuntu 22.04 job; `full` continues on that same runner after quick passes.
There are no push, pull-request or scheduled triggers. Nix and macOS remain
separate manual workflows and are not launched by either Linux selection.

## Scope

| Selection | Checks |
| --- | --- |
| Quick | Pinned setup/source checks and repeatable setup, CI orchestration contracts, bootstrap contracts, scaffold query, owned .NET style/warnings, runner contracts, graph-export suite, core and extension Starlark analysis |
| Full | Quick, then the remaining e2e modules, graph execution, handoff/discovery, graph cache, multi-language, full package cache, PrivateAssets/restore semantics, configured-node baseline/execution, lifecycle and synthetic-scale suites |
| Nix (separate) | Existing Nix setup, tooling and runtime-closure/e2e lane; request when Nix or runtime coverage is needed |
| macOS (separate) | Existing Starlark and selected Serilog qualification lane |

Quick still restores dependencies and builds repository tooling. It is cheaper
than full acceptance, not a build-free lint pass. Full preserves the suites from
the three previous non-Nix Linux workflows; it does not mean every test directory
or the separate Serilog/Nix lanes. Tests keep their existing prerequisite skips.

The former three workflows defined ten jobs in total. One full dispatch now uses
one job, avoids repeated tool acquisition and runs graph export, replay, binary
packages and runner contracts once each. Execution is sequential and stops at the
first failure; later suites have no evidence in that run. The timeout is 90 minutes.
This reduces duplicate work; runner-minute and wall-time savings are not measured.

Tool archive caching covers `.cache/downloads`, keyed by architecture, pins and
installer source. Setup still extracts downloads and verifies their checksums.
The second cache covers only `.cache/nuget/packages` for repository tooling.
Separate restore/save actions save verified downloads after repeatable setup and
tooling packages after quick checks, before full acceptance. A later acceptance
failure therefore does not discard newly acquired dependencies. Exact cache hits
skip saving; failures before a cache's save step do not publish that cache.
Isolated fixture package roots, bin/obj outputs, Bazel action caches and acceptance
workspaces are not included. Existing cold-cache and relocation controls remain
unchanged. Restoring a tool cache does not prove a network-fresh bootstrap.
Evidence uploads retain the former Linux log/report patterns for seven days.

## Local execution and verification

After acquiring native pinned tools, the same commands run locally:

```sh
bash scripts/setup.sh                 # Linux; includes source/tool checks
bash scripts/ci-linux.sh quick
bash scripts/ci-linux.sh full         # includes quick, then acceptance
```

CI invokes `quick` followed conditionally by `acceptance` to avoid repeating quick.
Use `full` locally when both phases are wanted. In a prepared Nix environment,
use `bash scripts/check.sh` instead of the Linux setup script first.

On 2026-09-07, local validation of the workflow refactor passed:

- `python3 -m unittest discover -s tests/ci -v`: five orchestration tests using
  stub commands, covering phase selection, early failure and duplicate e2e prevention.
- Ruby YAML parsing of all three remaining workflow files, plus assertions that
  cache saves follow their acquisition checks and precede full acceptance, reuse
  the restore keys/paths, and skip exact cache hits.
- `bash -n scripts/ci-linux.sh` and `git diff --check`.

These validate configuration and command orchestration, not native build behavior.
The quick/full native suites and GitHub cache/upload integration have not run for
this refactor. No GitHub dispatch was performed; publishing the configuration
does not trigger a validation run.
