# R04 pinned Serilog library adapter acceptance

The pinned selected-inner library passes all eight native macOS acceptance
controls: cold, unchanged, five independent mutations and producer-free relocated
disk recovery. This qualifies the library slice, not the unchanged upstream test
project or general package/generator support. Failures remain recorded as
`accepted=false` with their precise stage; the configured test never converts a
production failure into a skip.

The input is a Git archive of unchanged upstream revision
`49b5339ce85385dc52d4d8e8f2b8308becf23506`, selected at its existing `net10.0`
inner build. Acquired PolySharp and ILLink package directories are copied into
the independent workspace. No bracket rewriting, signing disablement, generator
disablement or framework retargeting is used for the baseline.

```sh
RULES_MSBUILD_SERILOG_SOURCE=/private/tmp/msbuild-serilog-baseline-3/source \
RULES_MSBUILD_SERILOG_PACKAGES=/private/tmp/msbuild-serilog-baseline-3/packages \
python3 -m unittest discover -s tests/serilog_adapter -v
```

`tools/probe_serilog_adapter.py` accepts explicit `--source`, `--package-cache`
and `--output` paths. Its default exercises all controls below. `--cases` selects
a smaller mutation subset; the report records that subset. Without acquisition
environment variables, the unittest is explicitly skipped and is not acceptance.

The ordinary and generated builds use separate copies of the same source. A real
consumer references the ordinary library at compilation, then runs against each
ordinary/generated DLL independently. It observes logging through a custom sink,
null rendering, resource logical names and bytes, assembly version, public key
token, the PE strong-name-signed flag, and actual emitted PolySharp internal types.
The key token/PE flag checks do not claim independent cryptographic verification
of the strong-name signature. The existing ordinary generated-source oracle
provides complementary evidence for the two PolySharp source outputs.

| Control | Required generated work and observable change |
| --- | --- |
| Cold | One native Serilog action; ordinary observation parity; unchanged upstream project declaration |
| Unchanged | Zero executions; identical consumer observation and complete bundle bytes/modes |
| Source | Change null rendering to `NULL`; one action; same changed ordinary result |
| Resource | Append an XML comment; one action; embedded resource hash changes identically |
| Key | Generate one replacement valid RSA key for both systems; one action; matching changed public key token and signed flag |
| Import | Change VersionPrefix 4.4.1 to 4.5.1; one action; assembly version becomes 4.5.0.0 |
| Generator option | Exclude IsExternalInit through the imported shared props; one action; actual emitted type disappears in both DLLs |
| Relocation | Remove producer output base/generated tree and both preparation trees; regenerate elsewhere; one disk hit, zero execution, all bundle bytes/modes match cold; execute the recovered DLL in the real consumer |

Mutations are applied independently to fresh upstream archives. They are explicit
controlled changes after the unchanged baseline, not edits used to make the
baseline supported. Preparation sources are deleted before each final generated
build. Ordinary binary logs, native execution logs, action diagnostics, complete
bundles and normalized hash/mode inventories are retained in the output directory.
The library's XML documentation must also be published.

## Measured native acceptance

The full unittest passed at acceptance revision `e97849b` in 75.484 seconds using
SDK 10.0.100, Bazel 8.4.2 and Nix Python 3.13.9 on macOS ARM64. Evidence:
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/serilog-adapter-3gsemaqt/probe/report.json`.
The elapsed duration is a shared-worker correctness result, not a performance
qualification. The host's unqualified `python3` changed to Python 3.9 during the
session; the successful final run used
`/nix/store/xcjk9ill54kjk8mzgq6yydnx9015lidg-python3-3.13.9/bin/python3` explicitly.
The safe archive extraction API requires Python 3.12 or newer.

Cold executed one `darwin-sandbox` action. Unchanged executed none. Source,
resource, replacement signing key, version import and generator-option edits each
executed exactly one native action and matched a separately built ordinary DLL's
observation. Every publication declared the exact eleven-analyzer inventory,
shared/nested props imports, key path/hash and resource LogicalName metadata.

Relocation removed the output base and generated producer tree, regenerated from
an unchanged archive at a different path, deleted its preparation tree and
restored one disk-cache hit with zero executions. All eight bundle files matched
cold bytes and executable bits, including the signed DLL, reference DLL, PDB,
XML documentation, dependency metadata and bundle manifests. The recovered DLL
passed real-consumer signing/resource/logging/generated-type checks. The full
canonical file inventory digest was
`d8ea2b60ff0056afbccb7382bb0cbc8d6cf067991753dd318ead62004103f388`.
The cold/recovered implementation DLL SHA-256 was
`241bb6b6023c1c089c027f0b179ad3b7da06b90bfd758f6f464425bf1c2ac926`.

The independent API helper also passed on both final cold/recovered DLLs, with
generated API text equal to the pinned approved bytes. Reports:
`/private/tmp/r04-api-final-cold-3gsemaqt/report.json` and
`/private/tmp/r04-api-final-relocated-3gsemaqt/report.json`. See
`serilog-api-oracle-findings.md` for its distinct scope; this does not execute the
unchanged upstream xUnit test project.

## Earlier failures and ordinary controls

At adapter revision `48a5439`, the ordinary unchanged source built successfully.
The consumer observed public key token `24C2F752A8E58A10`, a set strong-name flag,
version `4.4.0.0`, exactly `ILLink.Substitutions.xml`, logging `Hello "Ada"`, null
rendering `null`, and both IsExternalInit/RequiresLocationAttribute generated types.
The resource hash was
`BF05638D566BEA7B12904B6A5E67102ED489D21BB44D723DA718D67E0A545509`.

Fresh graph export then rejected the library with `stale-restore: evaluated direct
package set differs from restore`. Evidence:
`/private/tmp/msbuild-serilog-adapter-initial/report.json`. No native Bazel action,
mutation or cache recovery acceptance was established by that initial run. The
subsequent native attempts exposed sandbox-symlink archive length, nested import
discovery, explicit Nix import staging, and CRLF/BOM hash normalization gaps. Their
production fixes were integrated before the successful full run above. The
harness also needed to unlink its previous read-only DLL copy before replacement.

This scope is the library only. The upstream approval-test entry, isolated test
execution, publishing/trimming/AOT, general generators, Linux qualification and
remote-cache behavior remain separate. Linux validation is deferred by user
instruction. Shared-worker runs establish correctness, not useful-performance
thresholds.

The five ordinary mutation oracles were independently exercised while production
support was pending. All produced the specified observable changes, including
successful real-consumer loading after the signing token changed, and actual
removal of IsExternalInit after the generator option changed. Evidence:
`/private/tmp/msbuild-serilog-ordinary-controls/report.json`. This validates the
oracles and mutations; it does not qualify their native adapter counterparts.

## R04 qualification extension

The subsequent [R02–R04 qualification](r02-r04-validation-findings.md) adds a real
PolySharp 1.15.0 → 1.16.0 package/analyzer mutation, exact missing-payload rejection,
and fresh consumers compiled against both cold and recovered reference assemblies
before execution with their matching implementations. The complete nine-case
library probe passes on native macOS ARM64. The unchanged upstream approval
Build/Test suite also passes separately, with forced test execution after recovery.
[Repeated comparative measurements](serilog-performance-findings.md) are separate
from correctness-suite durations and do not extend Linux or remote-worker claims.
