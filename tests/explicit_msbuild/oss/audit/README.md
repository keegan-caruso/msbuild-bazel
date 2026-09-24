# Compatibility contract probes

These focused probes call the existing runner validators with minimal evaluated
MSBuild declarations. They are not upstream builds and do not change the rules.
Run on the qualified Linux ARM64 SDK environment after building `ExplicitBuild`:

```sh
mkdir -p /tmp/contract-audit
cp tests/explicit_msbuild/oss/audit/Contracts.cs.txt /tmp/contract-audit/Program.cs
cp tests/explicit_msbuild/oss/Inventory.csproj.txt /tmp/contract-audit/Audit.csproj
"$RULES_MSBUILD_DOTNET_ROOT/dotnet" build /tmp/contract-audit/Audit.csproj -c Release
"$RULES_MSBUILD_DOTNET_ROOT/dotnet" /tmp/contract-audit/bin/Release/net10.0/Audit.dll \
  "$PWD/tools/ExplicitBuild/bin/Release/net10.0"
```

Two positive controls accept ordinary and analyzer project references. Four
negative controls confirm rejection of build-only project references, treating a
build-only dependency as an analyzer, a file-valued task property, and an unresolved
assembly reference awaiting target-time package conversion. Any unexpected result
fails the probe. Reflection intentionally tests the internal contract without
introducing a public production API solely for this audit.
