#!/usr/bin/env bash
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
# One SDK declaration supplies both compilation and the web app's execution host.
sed -i 's/Microsoft.NET.Sdk"/Microsoft.NET.Sdk.Web"/' App/App.csproj
mkdir -p App/Pages App/wwwroot
printf '@page\n<p>page-v1</p>\n' > App/Pages/Index.cshtml
printf 'asset-v1\n' > App/wwwroot/message.txt
cat > App/Program.cs <<'CS'
using System;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Runtime.InteropServices;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.Extensions.DependencyInjection;
using Hello;

var builder = WebApplication.CreateBuilder(new WebApplicationOptions { Args = args, ContentRootPath = AppContext.BaseDirectory });
builder.WebHost.UseUrls("http://127.0.0.1:0");
builder.Services.AddRazorPages();
await using var app = builder.Build();
app.UseStaticFiles();
app.MapStaticAssets();
app.MapRazorPages();
app.MapGet("/hello", () => Message.Text());
await app.StartAsync();
try
{
    var address = app.Services.GetRequiredService<IServer>().Features.Get<IServerAddressesFeature>().Addresses.Single();
    using var client = new HttpClient { BaseAddress = new Uri(address), Timeout = TimeSpan.FromSeconds(10) };
    var response = await client.GetStringAsync("/hello");
    if (response != Message.Text()) throw new Exception("Unexpected HTTP response: " + response);
    Console.WriteLine("HTTP: " + response);
    var page = await client.GetStringAsync("/Index");
    if (!page.Contains("page-", StringComparison.Ordinal)) throw new Exception("Unexpected Razor page: " + page);
    Console.WriteLine("PAGE: " + page.Trim());
    var asset = Path.Combine(AppContext.BaseDirectory, "wwwroot", "message.txt");
    if (File.Exists(asset))
    {
        var content = await client.GetStringAsync("/message.txt");
        if (content != await File.ReadAllTextAsync(asset)) throw new Exception("Unexpected static asset: " + content);
        Console.WriteLine("ASSET: " + content.Trim());
    }
    else if (Environment.GetEnvironmentVariable("EXPECT_PUBLISHED_ASSETS") == "1")
    {
        throw new Exception("Missing published static asset");
    }
    Console.WriteLine("FRAMEWORK: " + typeof(WebApplication).Assembly.Location);
    Console.WriteLine(RuntimeInformation.FrameworkDescription);
}
finally
{
    await app.StopAsync();
}
CS
# Match compiler path maps for paired raw builds in the graph namespace.
cat > Directory.Build.props <<'XML'
<Project><PropertyGroup><PathMap>/__rules_msbuild_graph/output/workspace=/_/workspace,/__rules_msbuild_graph/sdk=/_/sdk</PathMap></PropertyGroup></Project>
XML
bazel build @dotnet//:files
execroot=$(bazel info execution_root)
sdk=$(dirname "$(realpath "$execroot/$(bazel cquery @dotnet//:files --output=files 2> "$TEST_TMPDIR/sdk-query.log" | grep '/sdk/dotnet$')")")
cp -R "$scratch/consumer" "$scratch/authored"
options=(--remote_cache= --disk_cache=)
if [[ -n "${SDK_WEB_CACHE_URL:-}" ]]; then
    options+=(--remote_cache="$SDK_WEB_CACHE_URL" --remote_cache_async=false --remote_download_outputs=all
        --action_env=RULES_MSBUILD_PROJECT_CACHE_URL="$SDK_WEB_CACHE_URL")
fi
python3 - <<'PY'
from pathlib import Path
p=Path('BUILD.bazel');text=p.read_text().replace('app_graph(name = "graph")','app_graph(name = "graph", linux_stable_paths = True)')
text+='''
app_graph(name="publish", target="Publish", linux_stable_paths=True)
msbuild_graph_binary(name="published_app", graph=":publish", project="App/App.csproj")
msbuild_graph_test(name="web_test", graph=":graph", project="App/App.csproj")
msbuild_graph_test(name="published_test", graph=":publish", project="App/App.csproj", env={"EXPECT_PUBLISHED_ASSETS":"1"})
'''
p.write_text(text)
PY
bazel run //:sync
bazel run //:sync -- --check
run_app() {
    bazel run "//:$1" "${options[@]}" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }
    assert_contains "$TEST_TMPDIR/$1.log" 'HTTP: Hello from MSBuild and Bazel'
    assert_contains "$TEST_TMPDIR/$1.log" "PAGE: <p>$2</p>"
    assert_contains "$TEST_TMPDIR/$1.log" '/shared/Microsoft.AspNetCore.App/10.0.11/'
    if [[ "$1" == published_app ]]; then assert_contains "$TEST_TMPDIR/$1.log" "ASSET: $3"; fi
}
run_app app page-v1 asset-v1
run_app published_app page-v1 asset-v1
bazel test //:web_test //:published_test //:tests "${options[@]}" --test_output=errors
publish_products() { (cd "$1/App/bin/Release/net10.0/publish"; find . -type f -print0 | sort -z | xargs -0 sha256sum); }
publish_products bazel-bin/publish.graph/workspace > "$TEST_TMPDIR/publish.sha256"
for mode in ordinary graph; do
    cp -a "$scratch/authored" "$scratch/raw-$mode"
    mkdir "$scratch/raw-$mode-scratch"
    graph=(); if [[ "$mode" == graph ]]; then graph=(-graphBuild); fi
    bash "$runner_dir/raw_namespace.sh" "$sdk" "$scratch/raw-$mode" "$scratch/raw-$mode-scratch" msbuild App/App.csproj -restore -t:Publish -m:4 "${graph[@]}" -p:Configuration=Release -p:UseSharedCompilation=false -p:NuGetAudit=false > "$TEST_TMPDIR/raw-$mode.log" 2>&1 || { cat "$TEST_TMPDIR/raw-$mode.log" >&2; exit 1; }
    publish_products "$scratch/raw-$mode" > "$TEST_TMPDIR/raw-$mode.sha256"
    cp "$scratch/raw-$mode/App/bin/Release/net10.0/publish/App.staticwebassets.endpoints.json" "$TEST_TMPDIR/raw-$mode.endpoints.json"
done
cp bazel-bin/publish.graph/workspace/App/bin/Release/net10.0/publish/App.staticwebassets.endpoints.json "$TEST_TMPDIR/graph.endpoints.json"
# The SDK records source/compression timestamps in Last-Modified response headers.
# Check every other byte and all endpoint metadata, normalizing only those values.
for mode in raw-ordinary raw-graph publish; do
    grep -v '  ./App.staticwebassets.endpoints.json$' "$TEST_TMPDIR/$mode.sha256" > "$TEST_TMPDIR/$mode.stable.sha256"
done
cmp "$TEST_TMPDIR/raw-ordinary.stable.sha256" "$TEST_TMPDIR/raw-graph.stable.sha256"
cmp "$TEST_TMPDIR/raw-graph.stable.sha256" "$TEST_TMPDIR/publish.stable.sha256"
python3 - "$TEST_TMPDIR" <<'PY'
import json,sys
from email.utils import parsedate_to_datetime
from pathlib import Path
def manifest(name):
    data=json.loads(Path(sys.argv[1],name+'.endpoints.json').read_text());count=0
    for endpoint in data['Endpoints']:
        for header in endpoint['ResponseHeaders']:
            if header['Name']=='Last-Modified':
                assert parsedate_to_datetime(header['Value']).tzinfo is not None
                header['Value']='<timestamp>';count+=1
    assert count>0
    return data
assert manifest('raw-ordinary')==manifest('raw-graph')==manifest('graph')
PY
# Razor and static content edits are already-declared inputs, requiring no sync.
sed -i 's/page-v1/page-v2/' App/Pages/Index.cshtml
printf 'asset-v2\n' > App/wwwroot/message.txt
run_app app page-v2 asset-v2
run_app published_app page-v2 asset-v2
bazel test //:web_test //:published_test "${options[@]}" --test_output=errors
publish_products bazel-bin/publish.graph/workspace > "$TEST_TMPDIR/edited.sha256"
if cmp -s "$TEST_TMPDIR/publish.sha256" "$TEST_TMPDIR/edited.sha256"; then echo 'Edits did not change published outputs' >&2; exit 1; fi
bazel shutdown
mkdir "$scratch/recovery"
tar -cf "$scratch/consumer.tar" App Library Tests MODULE.bazel MODULE.bazel.lock BUILD.bazel global.json Directory.Build.props graph.generated.json graph.generated.bzl
tar -xf "$scratch/consumer.tar" -C "$scratch/recovery"
cd "$scratch/recovery"
fresh() {
    "$BIT_BAZEL_BINARY" --batch --ignore_all_rc_files --output_base="$scratch/$1" "${@:2}" \
        --repository_cache="${RULES_MSBUILD_TEST_REPOSITORY_CACHE:-$scratch/repository-cache}"
}
fresh recovered test //:published_test "${options[@]}" --lockfile_mode=error --test_output=all --execution_log_json_file="$TEST_TMPDIR/recovered.execution.json"
# Explicitly execute the recovered app, even if Bazel recovers the test result.
fresh recovered run //:published_app "${options[@]}" --lockfile_mode=error \
    --run_under='env -u RUNFILES_DIR -u RUNFILES_MANIFEST_FILE -u TEST_SRCDIR' > "$TEST_TMPDIR/recovered-app.log" 2>&1 || { cat "$TEST_TMPDIR/recovered-app.log" >&2; exit 1; }
assert_contains "$TEST_TMPDIR/recovered-app.log" 'PAGE: <p>page-v2</p>'
assert_contains "$TEST_TMPDIR/recovered-app.log" 'ASSET: asset-v2'
publish_products bazel-bin/publish.graph/workspace > "$TEST_TMPDIR/recovered.sha256"
cmp "$TEST_TMPDIR/edited.sha256" "$TEST_TMPDIR/recovered.sha256"
if [[ -n "${SDK_WEB_CACHE_URL:-}" ]]; then
    python3 - "$TEST_TMPDIR/recovered.execution.json" <<'PY'
import json,sys
s=open(sys.argv[1]).read();decoder=json.JSONDecoder();graphs=[]
while s.strip():
    action,end=decoder.raw_decode(s.lstrip());s=s.lstrip()[end:]
    if action.get('mnemonic')=='MSBuildGraph':graphs.append(action)
assert len(graphs)==1 and graphs[0].get('cacheHit') and graphs[0].get('runner')=='remote cache hit',graphs
PY
    fresh project-recovery test //:published_test "${options[@]}" --noremote_accept_cached --remote_upload_local_results=false --lockfile_mode=error --test_output=all
    python3 - <<'PY'
import json
from pathlib import Path
report=json.loads(Path('bazel-bin/publish.graph/report.json').read_text())
assert (report['hits'],report['misses'])==(3,0),report
PY
    publish_products bazel-bin/publish.graph/workspace > "$TEST_TMPDIR/project-recovery.sha256"
    cmp "$TEST_TMPDIR/edited.sha256" "$TEST_TMPDIR/project-recovery.sha256"
fi
echo 'PASS: SDK-only Web/Razor Build/test/Publish, raw output parity, content edits and fresh-cache execution'
