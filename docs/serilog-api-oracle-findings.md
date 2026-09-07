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

Set `SPIKE_DOTNET_ROOT` to the pinned SDK, or pass `--dotnet-root`. Exit status is
zero for matching API and one for a mismatch; setup/generation failures raise an
error. Retained evidence contains the approved and actual text, a unified diff,
archive pins, assembly hash and command logs. Comparison preserves all text and
internal whitespace, normalizing CRLF/LF and final newlines only. The helper
runs locally and does not establish hermetic or upstream test-runner acceptance.
