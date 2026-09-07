# R04 pinned Serilog library adapter acceptance

The independent harness is implemented; initial native adapter acceptance is
blocked by production package/input discovery support. A rejection is recorded
as `accepted=false` with its precise stage, and the probe exits nonzero. The
configured native test is not converted to a skip when production fails.

The input is a Git archive of unchanged upstream revision
`49b5339ce85385dc52d4d8e8f2b8308becf23506`, selected at its existing `net10.0`
inner build. Acquired PolySharp and ILLink package directories are copied into
the independent workspace. No bracket rewriting, signing disablement, generator
disablement or framework retargeting is used for the baseline.

```sh
SPIKE_SERILOG_SOURCE=/private/tmp/msbuild-serilog-baseline-3/source \
SPIKE_SERILOG_PACKAGES=/private/tmp/msbuild-serilog-baseline-3/packages \
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

## Initial measured evidence

At adapter revision `48a5439`, the ordinary unchanged source built successfully.
The consumer observed public key token `24C2F752A8E58A10`, a set strong-name flag,
version `4.4.0.0`, exactly `ILLink.Substitutions.xml`, logging `Hello "Ada"`, null
rendering `null`, and both IsExternalInit/RequiresLocationAttribute generated types.
The resource hash was
`BF05638D566BEA7B12904B6A5E67102ED489D21BB44D723DA718D67E0A545509`.

Fresh graph export then rejected the library with `stale-restore: evaluated direct
package set differs from restore`. Evidence:
`/private/tmp/msbuild-serilog-adapter-initial/report.json`. No native Bazel action,
mutation or cache recovery acceptance is claimed by that initial run. Package
policy and post-resolution input discovery are being implemented independently.

This scope is the library only. The upstream approval-test entry, isolated test
execution, publishing/trimming/AOT, general generators, Linux qualification and
remote-cache behavior remain separate. Linux validation is deferred by user
instruction. Shared-worker runs establish correctness, not useful-performance
thresholds.
