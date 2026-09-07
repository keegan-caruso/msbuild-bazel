# Standalone Serilog API approval oracle

`tools/probe_serilog_api.py` independently runs PublicApiGenerator 11.1.0 against
any supplied assembly and compares the result with the pinned upstream
`Serilog.approved.txt`. It uses the unchanged upstream ApiApprovalTests options:
exclude assembly attributes and System.Diagnostics.DebuggerDisplayAttribute.
This is not execution of the upstream xunit/Shouldly approval test project.

The helper pins and verifies SHA256 hashes of the upstream test, approval file,
and test project from Serilog revision 49b5339ce85385dc52d4d8e8f2b8308becf23506.
It also verifies acquired PublicApiGenerator 11.1.0, Mono.Cecil 0.11.5 and
System.CodeDom 8.0.0 archives before restoring a separate helper from a local
feed. The archive hashes are recorded in `tools/SerilogApiOracle/pins.json` and
each report. No graph package policy is expanded. The supplied DLL's hash is
recorded and checked again after generation.

```sh
python3 tools/probe_serilog_api.py \
  --source /path/to/pinned/serilog \
  --packages /path/to/acquired/package-cache \
  --assembly /path/to/ordinary-or-recovered/Serilog.dll \
  --output /path/to/fresh/evidence
```

Set `RULES_MSBUILD_DOTNET_ROOT` to the pinned SDK, or pass `--dotnet-root`. Exit status is
zero for matching API and one for a mismatch; setup/generation failures raise an
error. Retained evidence contains the approved and actual text, a unified diff,
archive pins, assembly hash and command logs. Comparison preserves all text and
internal whitespace, normalizing CRLF/LF and final newlines only. The helper
runs locally and does not establish hermetic or upstream test-runner acceptance.

On macOS ARM64 with SDK 10.0.100, the acquired ordinary net10.0 Serilog DLL
matched the upstream approved API. A supplied incompatible assembly produced a
failed report and nonempty diff. The opt-in `tests/serilog_api` test passed in
2.088 seconds, covering both comparisons. Evidence is retained at
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/serilog-api-oracle-dw1rzs0k`,
with harness log `/private/tmp/r04-api-oracle-tests.log`. This result measures
the existing ordinary library baseline; adapter and recovered bundles must be
passed independently before claiming equivalent public API there.

## Native cold and relocated bundle approval

The final native Serilog adapter probe at `serilog-adapter-3gsemaqt/probe`
completed its eight cases. The standalone oracle was independently run against
both `evidence/cold/bundle/artifacts/src/Serilog/bin/Release/net10.0/Serilog.dll`
and the corresponding `evidence/relocated` DLL, using explicit Nix Python 3.13.9
and SDK 10.0.100. Both passed. The generated API text in both cases is byte-for-byte
identical to the pinned upstream approval file (SHA256
`ba5f809321f00be804d5ef5839f1654404fc87641a077429edb196ecaf74d1ef`), without needing
line-ending normalization. The cold and relocated DLL bytes are also identical
(SHA256 `241bb6b6023c1c089c027f0b179ad3b7da06b90bfd758f6f464425bf1c2ac926`).

Independent reports, actual/approved text, and helper build logs are retained at
`/private/tmp/r04-api-final-cold-3gsemaqt` and
`/private/tmp/r04-api-final-relocated-3gsemaqt`. Native probe evidence is under
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/serilog-adapter-3gsemaqt/probe`.
An earlier successful cold assembly from `serilog-adapter-sb57w6os` also passed;
its report is `/private/tmp/r04-api-native-cold-sb57w6os/report.json`.

These comparisons establish the approved public API for the measured ordinary,
native cold, and relocated library artifacts. The unchanged upstream xunit /
Shouldly approval test project remains a separate unexecuted acceptance slice.
