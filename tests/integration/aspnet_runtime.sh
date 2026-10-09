#!/usr/bin/env bash
set -euo pipefail
aspnet_metadata=()
for file in $ASPNET_TEST_METADATA; do aspnet_metadata+=("$(realpath "$file")"); done
core_metadata=$(realpath "$CORE_TEST_METADATA")
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
python3 - "${aspnet_metadata[@]}" "$core_metadata" <<'PY'
import json,sys
from pathlib import Path
core=json.loads(Path(sys.argv[3]).read_text())['releases'][0]['runtime']
module=Path('MODULE.bazel').read_text()
for name,file in zip(['web','future'],sys.argv[1:3],strict=True):
    metadata=json.loads(Path(file).read_text())
    if name=='web':metadata['releases'][0]['runtime']=core
    p=Path(name+'-metadata.json');p.write_text(json.dumps(metadata))
    version=metadata['releases'][0]['aspnetcore-runtime']['version']
    module+='\ndotnet.runtime(name='+json.dumps(name)+',version='+json.dumps(version)+',kind="aspnetcore",platforms=["linux-arm64"],metadata_urls=['+json.dumps(p.resolve().as_uri())+'])\nuse_repo(dotnet,'+json.dumps(name)+')\n'
module+='\ndotnet.runtime(name="core",version="9.0.20",platforms=["linux-arm64"],metadata_urls=['+json.dumps(Path('web-metadata.json').resolve().as_uri())+'])\nuse_repo(dotnet,"core")\n'
Path('MODULE.bazel').write_text(module)
p=Path('global.json');p.write_text(p.read_text().replace('10.0.400','9.0.318'))
for p in Path('.').glob('*/*.csproj'):
    p.write_text(p.read_text().replace('net10.0','net9.0'))
p=Path('App/App.csproj');p.write_text(p.read_text().replace('Microsoft.NET.Sdk"','Microsoft.NET.Sdk.Web"'))
p=Path('BUILD.bazel');text=p.read_text().replace('app_graph(name = "graph")','app_graph(name = "graph", linux_stable_paths = True)')
for name in ['core','web','future']:
    text+='\nmsbuild_graph_binary(name='+json.dumps(name+'_app')+',graph=":graph",project="App/App.csproj",runtime_host="@'+name+'//:runtime")\n'
text+='\nmsbuild_graph_test(name="web_test",graph=":graph",project="App/App.csproj",runtime_host="@web//:runtime")\n'
text+='\nmsbuild_graph_test(name="future_test",graph=":graph",project="App/App.csproj",runtime_host="@future//:runtime")\n'
p.write_text(text)
PY
cat > App/Program.cs <<'CS'
using System;
using System.Linq;
using System.Net.Http;
using System.Runtime.InteropServices;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.Extensions.DependencyInjection;
using Hello;

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls("http://127.0.0.1:0");
await using var app = builder.Build();
app.MapGet("/", () => Message.Text());
await app.StartAsync();
try
{
    var addresses = app.Services.GetRequiredService<IServer>().Features.Get<IServerAddressesFeature>();
    using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };
    var response = await client.GetStringAsync(addresses.Addresses.Single());
    if (response != Message.Text()) throw new Exception("Unexpected response: " + response);
    Console.WriteLine("HTTP: " + response);
    Console.WriteLine(RuntimeInformation.FrameworkDescription);
    Console.WriteLine("ASP.NET: " + typeof(WebApplication).Assembly.Location);
}
finally
{
    await app.StopAsync();
}
CS
options=(--remote_cache= --disk_cache=)
if [[ -n "${RUNTIME_CACHE_URL:-}" ]]; then
    options+=(--remote_cache="$RUNTIME_CACHE_URL" --remote_cache_async=false --remote_download_outputs=all
        --action_env=RULES_MSBUILD_PROJECT_CACHE_URL="$RUNTIME_CACHE_URL")
fi
expect_failure() {
    if "$@" > "$TEST_TMPDIR/failure.log" 2>&1; then
        cat "$TEST_TMPDIR/failure.log" >&2; echo 'Expected failure' >&2; exit 1
    fi
}
fresh() {
    "$BIT_BAZEL_BINARY" --batch --nosystem_rc --nohome_rc --noworkspace_rc --output_base="$scratch/$1" "${@:2}" \
        --repository_cache="${RULES_MSBUILD_TEST_REPOSITORY_CACHE:-$scratch/repository-cache}"
}
bazel run //:sync
bazel run //:web_app "${options[@]}" > "$TEST_TMPDIR/web.log" 2>&1 || { cat "$TEST_TMPDIR/web.log" >&2; exit 1; }
assert_contains "$TEST_TMPDIR/web.log" 'HTTP: Hello from MSBuild and Bazel'
assert_contains "$TEST_TMPDIR/web.log" '.NET 9.0.20'
assert_contains "$TEST_TMPDIR/web.log" '/shared/Microsoft.AspNetCore.App/9.0.20/'
assert_contains graph.generated.json '"SdkVersion": "9.0.318"'
bazel test //:web_test "${options[@]}" --test_output=all
expect_failure bazel run //:core_app "${options[@]}"
assert_contains "$TEST_TMPDIR/failure.log" 'Microsoft.AspNetCore.App'
assert_contains "$TEST_TMPDIR/failure.log" 'You must install or update .NET'
python3 - <<'PY'
import json
from pathlib import Path
facts=next(v['runtime-v1'] for v in json.loads(Path('MODULE.bazel.lock').read_text())['facts'].values() if 'runtime-v1' in v)
selections={tuple(json.loads(k)[2:]):v for k,v in facts.items() if json.loads(k)[0]=='9.0.20'}
assert set(selections)=={(),('aspnetcore',)},selections
core=selections[()]['platforms']['linux-arm64']
web=selections[('aspnetcore',)]['platforms']['linux-arm64']
assert '/dotnet-runtime-' in core['urls'][0],core
assert '/aspnetcore-runtime-9.0.20-' in web['urls'][0],web
assert core['integrity']!=web['integrity']
PY
expect_failure bazel run //:future_app "${options[@]}"
assert_contains "$TEST_TMPDIR/failure.log" 'You must install or update .NET'
sed -i 's@<TargetFramework>@<RollForward>Major</RollForward><TargetFramework>@' App/App.csproj
bazel run //:sync
bazel run //:future_app "${options[@]}" > "$TEST_TMPDIR/future.log" 2>&1 || { cat "$TEST_TMPDIR/future.log" >&2; exit 1; }
assert_contains "$TEST_TMPDIR/future.log" '.NET 10.0.12'
assert_contains "$TEST_TMPDIR/future.log" '/shared/Microsoft.AspNetCore.App/10.0.12/'
bazel test //:future_test "${options[@]}" --test_output=all
products() { (cd bazel-bin/graph.graph/workspace; find App/bin Library/bin Tests/bin -type f -print0 | sort -z | xargs -0 sha256sum); }
products > "$TEST_TMPDIR/seed.sha256"
bazel shutdown
# Independent source directory and output base; metadata is no longer available.
rm web-metadata.json future-metadata.json
mkdir "$scratch/consumer-recovery"
tar -cf "$scratch/consumer.tar" App Library Tests MODULE.bazel MODULE.bazel.lock BUILD.bazel global.json graph.generated.json graph.generated.bzl
tar -xf "$scratch/consumer.tar" -C "$scratch/consumer-recovery"
cd "$scratch/consumer-recovery"
fresh recovered test //:future_test "${options[@]}" --lockfile_mode=error --test_output=all --execution_log_json_file="$TEST_TMPDIR/recovered.execution.json"
# Preserve wrapper runfiles, but clear the outer test environment for the app itself.
fresh recovered run //:future_app "${options[@]}" --lockfile_mode=error \
    --run_under='env -u RUNFILES_DIR -u RUNFILES_MANIFEST_FILE -u TEST_SRCDIR' \
    > "$TEST_TMPDIR/recovered-app.log" 2>&1 || { cat "$TEST_TMPDIR/recovered-app.log" >&2; exit 1; }
assert_contains "$TEST_TMPDIR/recovered-app.log" 'HTTP: Hello from MSBuild and Bazel'
assert_contains "$TEST_TMPDIR/recovered-app.log" '/shared/Microsoft.AspNetCore.App/10.0.12/'
products > "$TEST_TMPDIR/recovered.sha256"
cmp "$TEST_TMPDIR/seed.sha256" "$TEST_TMPDIR/recovered.sha256"
if [[ -n "${RUNTIME_CACHE_URL:-}" ]]; then
    python3 - "$TEST_TMPDIR/recovered.execution.json" <<'PY'
import json,sys
s=open(sys.argv[1]).read();decoder=json.JSONDecoder();graphs=[]
while s.strip():
    action,end=decoder.raw_decode(s.lstrip());s=s.lstrip()[end:]
    if action.get('mnemonic')=='MSBuildGraph':graphs.append(action)
assert len(graphs)==1 and graphs[0].get('cacheHit') and graphs[0].get('runner')=='remote cache hit',graphs
PY
    # Force graph execution to qualify the MSBuild project-cache recovery as well.
    fresh project-recovery test //:future_test "${options[@]}" --noremote_accept_cached --remote_upload_local_results=false --lockfile_mode=error --test_output=all
    python3 - <<'PY'
import json
from pathlib import Path
report=json.loads(Path('bazel-bin/graph.graph/report.json').read_text())
assert (report['hits'],report['misses'])==(3,0),report
PY
    products > "$TEST_TMPDIR/project-recovery.sha256"
    cmp "$TEST_TMPDIR/seed.sha256" "$TEST_TMPDIR/project-recovery.sha256"
fi
case "$("$BIT_BAZEL_BINARY" --version)" in
    'bazel 9.3.'*)
        printf 'block .*\n' > "$scratch/downloader.config"
        fresh blocked query 'deps(@web//:runtime) + deps(@future//:runtime)' --lockfile_mode=error --downloader_config="$scratch/downloader.config"
        ;;
esac
# A verified archive still needs the complete selected framework layout.
mkdir -p incomplete
printf '#!/bin/sh\nexit 0\n' > incomplete/dotnet
chmod +x incomplete/dotnet
for component in core aspnet; do
    if [[ "$component" == aspnet ]]; then mkdir -p incomplete/shared/Microsoft.NETCore.App/42.0.7; fi
    tar -czf "incomplete-$component.tar.gz" -C incomplete .
    python3 - "$component" <<'PY'
import hashlib,json,sys
from pathlib import Path
component=sys.argv[1];archive=Path('incomplete-'+component+'.tar.gz').resolve()
metadata={'releases':[{'aspnetcore-runtime':{'version':'42.0.7','files':[{'rid':'linux-arm64','name':'aspnetcore-runtime-linux-arm64.tar.gz','url':archive.as_uri(),'hash':hashlib.sha512(archive.read_bytes()).hexdigest()}]}}]}
p=Path('incomplete-'+component+'.json');p.write_text(json.dumps(metadata))
p_module=Path('MODULE.bazel')
p_module.write_text(p_module.read_text()+'\ndotnet.runtime(name="incomplete_'+component+'",version="42.0.7",kind="aspnetcore",platforms=["linux-arm64"],metadata_urls=['+json.dumps(p.resolve().as_uri())+'])\nuse_repo(dotnet,"incomplete_'+component+'")\n')
PY
    expect_failure bazel query "deps(@incomplete_$component//:runtime)"
    assert_contains "$TEST_TMPDIR/failure.log" 'ASP.NET runtime archive is missing declared layout component:'
    if [[ "$component" == core ]]; then
        assert_contains "$TEST_TMPDIR/failure.log" 'shared/Microsoft.NETCore.App'
    else
        assert_contains "$TEST_TMPDIR/failure.log" 'shared/Microsoft.AspNetCore.App/42.0.7'
    fi
done
echo 'PASS: complete ASP.NET runtimes, CoreCLR fact isolation, HTTP app/test, roll-forward and fresh-cache recovery'
