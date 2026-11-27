"""Create launchers for explicit executable and test projects."""

load(":paths.bzl", _RUNTIME_TOOLCHAIN = "RUNTIME_TOOLCHAIN", _quote = "quote", _runfile = "runfile")
load(":providers.bzl", "MSBuildRuntimeInfo", "MSBuildTestToolInfo")
load(":shell_launcher.bzl", "shell_launcher", "shell_runfiles", "write_shell_script")

def _runtime_host(ctx):
    host = ctx.attr.runtime_host[MSBuildRuntimeInfo] if ctx.attr.runtime_host else None
    if host == None and ctx.toolchains[_RUNTIME_TOOLCHAIN] != None:
        host = ctx.toolchains[_RUNTIME_TOOLCHAIN].runtime
    if host == None:
        fail("No SDK runtime matches the target platform; declare a compatible SDK platform or runtime_host")
    return host

def create_executable_launcher(ctx, assembly, runtime, runtime_data, test):
    """Run executable outputs using only their declared runtime host.

    Args:
        ctx: Project rule context.
        assembly: Entry assembly filename.
        runtime: Application output tree.
        runtime_data: Runtime data file destinations.
        test: Whether to apply executable test options.

    Returns:
        Executable and optional test environment providers.
    """
    host = _runtime_host(ctx)
    readonly = test and ctx.attr.direct_executable_smoke
    if readonly:
        if ctx.attr.expected_exit_code != 0:
            fail("direct_executable_smoke requires expected_exit_code = 0")
        for attribute in ["test_settings", "test_settings_output", "test_filter_argument", "allow_empty_tests", "test_diagnostics", "test_output_dirs", "test_working_directory", "test_runner", "test_adapters", "data_paths"]:
            if getattr(ctx.attr, attribute):
                fail("direct_executable_smoke does not support " + attribute)
        if host.launch_mode != "dotnet":
            fail("direct_executable_smoke requires a dotnet runtime host")
        if host.environment:
            fail("direct_executable_smoke does not support custom runtime host environment")
    if test and (ctx.attr.test_settings or ctx.attr.test_settings_output):
        fail("Executable test filtering/settings is not supported")
    for path in [row.destination for row in runtime_data.to_list()] + (ctx.attr.test_output_dirs if test else []):
        if not path or path.startswith("/") or "\\" in path or any([part in ["", ".", ".."] for part in path.split("/")]) or any([char in path for char in ["\n", "\r"]]):
            fail("Runtime destinations must be safe relative paths: " + path)
    launcher = ctx.actions.declare_file(ctx.label.name)
    setup = ["resolve_runfile " + _quote(_runfile(ctx, row.file)) + "; copy_input \"$RULES_MSBUILD_RESOLVED_RUNFILE\" \"$temporary/\"" + _quote(row.destination) for row in runtime_data.to_list()]
    outputs = ["output_directory " + _quote(path) for path in ctx.attr.test_output_dirs] if test else []
    collection = ["copy_output " + _quote(path) + " || copy_status=1" for path in ctx.attr.test_output_dirs] if test else []
    owned_environment = ["CORE_ROOT", "DOTNET_ROOT", "DOTNET_HOST_PATH", "DOTNET_MULTILEVEL_LOOKUP"] + ["DOTNET_ROOT_" + architecture for architecture in ["X64", "X86", "ARM", "ARM64"]]
    host_environment = " ".join([_quote(name + "=" + value) for name, value in host.environment.items() if name not in owned_environment])
    script = """#!/usr/bin/env bash
set -euo pipefail
fail() { echo "msbuild launcher: $*" >&2; exit 1; }
resolve_runfile %s || fail 'declared runtime host is missing or not executable'
host_root="$RULES_MSBUILD_RESOLVED_RUNFILE"
native_host_root="$RULES_MSBUILD_NATIVE_RUNFILE"
entry=%s
host="$host_root/$entry"
native_host="$native_host_root/$entry"
resolve_runfile %s
input="$RULES_MSBUILD_RESOLVED_RUNFILE"
native_input="$RULES_MSBUILD_NATIVE_RUNFILE"
temporary=''
child=''
private_group=0
output=''
copy_output() {
  local source="$temporary/$1" target="$output/files/$1"
  [[ -d "$source" ]] || return 0
  mkdir -p -- "$target" && cp -R -- "$source/." "$target/"
}
kill_tree() {
  local descendant
  for descendant in $(ps -axo pid=,ppid= | awk -v parent="$1" '$2 == parent { print $1 }'); do
    kill_tree "$descendant"
  done
  kill -KILL "$1" 2>/dev/null || true
}
kill_windows_tree() {
  local native_pid system
  native_pid="$(ps -p "$1" | awk -v owned="$1" 'NR == 1 { for (i = 1; i <= NF; i++) if ($i == "WINPID") column = i } NR > 1 && $1 == owned && column { print $column }' || true)"
  case "$native_pid" in ''|*[!0-9]*) return 1 ;; esac
  system="${SYSTEMROOT:-${SystemRoot:-${WINDIR:-${windir:-}}}}"
  [[ -n "$system" ]] || return 1
  system="$(cygpath -au "$system")"
  "$system/System32/taskkill.exe" /F /T /PID "$native_pid" >/dev/null
}
cleanup() {
  local copy_status=0 kill_status=0
  if [[ -n "$child" ]]; then
    case "$(uname -s)" in
      MINGW*|MSYS*|CYGWIN*)
        if kill_windows_tree "$child"; then
          wait "$child" 2>/dev/null || true
        else
          kill_status=1
          kill -KILL "$child" 2>/dev/null || true
        fi
        ;;
      *)
        if [[ "$private_group" = 1 ]]; then
          kill -KILL -- "-$child" 2>/dev/null || true
        else
          kill_tree "$child"
        fi
        ;;
    esac
  fi
  if [[ -n "$temporary" ]]; then
    case "$(uname -s)" in
      MINGW*|MSYS*|CYGWIN*)
        if [[ -n "$output" ]]; then
%s
        fi
        ;;
    esac
    rm -rf -- "$temporary"
  fi
  [[ "$kill_status" = 0 ]] || fail 'Failed to terminate the owned Windows process tree'
  [[ "$copy_status" = 0 ]] || fail 'Failed to collect test output directories'
}
trap cleanup EXIT
cancel() { trap '' TERM INT; exit "$1"; }
trap 'cancel 143' TERM
trap 'cancel 130' INT
copy_input() {
  mkdir -p -- "$(dirname -- "$2")"
  if [[ -e "$2" || -L "$2" ]]; then
    [[ -f "$2" ]] && cmp -s -- "$1" "$2" || fail "Conflicting runtime/input destination: $2"
  else
    cp -pL -- "$1" "$2"
    chmod u+w "$2"
  fi
}
output_directory() {
  local link="$temporary/$1" target="$output/files/$1"
  [[ ! -e "$link" && ! -L "$link" ]] || fail "Test output directory collides with a runtime input: $1"
  mkdir -p -- "$target" "$(dirname -- "$link")"
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) mkdir -p -- "$link" ;;
    *) ln -s -- "$target" "$link" ;;
  esac
}
is_test=%s
readonly=%s
if [[ "$is_test" = 1 ]]; then
  [[ -z "${TESTBRIDGE_TEST_ONLY:-}" ]] || fail 'Executable test filtering/settings is not supported'
  case "${TEST_TOTAL_SHARDS:-0}" in 0|1) ;; *) fail 'test sharding is not supported' ;; esac
  case "${TEST_SHARD_INDEX:-0}" in 0) ;; *) fail 'test sharding is not supported' ;; esac
fi
[[ -x "$host" ]] || fail 'declared runtime host is missing or not executable'
[[ -f "$input/"%s ]] || fail 'declared entry assembly is missing'
if [[ "$readonly" = 1 ]]; then
  runtime="$input"
else
  temporary=$(mktemp -d "${TEST_TMPDIR:-${TMPDIR:-/tmp}}/msbuild-run-XXXXXXXX")
  runtime="$temporary/"%s
  mkdir -p -- "$runtime"
  cp -pRL "$input/." "$runtime/"
  chmod -R u+w "$runtime"
fi
%s
native_runtime="$runtime"
if [[ "$readonly" = 1 ]]; then
  native_runtime="$native_input"
else
  case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) native_runtime="$(native_path "$runtime")" ;; esac
fi
unset CORE_ROOT
%s
export DOTNET_ROOT="$native_host_root" DOTNET_HOST_PATH="$native_host" DOTNET_MULTILEVEL_LOOKUP=0
export DOTNET_ROOT_X64="$DOTNET_ROOT" DOTNET_ROOT_X86="$DOTNET_ROOT"
export DOTNET_ROOT_ARM="$DOTNET_ROOT" DOTNET_ROOT_ARM64="$DOTNET_ROOT"
if [[ "$is_test" = 1 && "$readonly" != 1 ]]; then
  output="${TEST_UNDECLARED_OUTPUTS_DIR:-$temporary/test-results}"
  case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) output="$(cygpath -au "$output")" ;; esac
  [[ "$output" = /* ]] || output="$PWD/$output"
  mkdir -p -- "$output"
%s
fi
launch=(env %s "$host" "$native_runtime/"%s "$@")
if [[ "$readonly" = 1 ]]; then exec "${launch[@]}"; fi
cd -- "$runtime"
# Keep terminal readers in the inherited foreground process group. Other
# launches own a group so cancellation also reaches descendants directly.
if [[ -t 0 ]]; then set +m; else set -m; private_group=1; fi
"${launch[@]}" <&0 &
child=$!
set +e
wait "$child"
status=$?
child=''
set -e
if [[ "$is_test" = 1 ]]; then
  if [[ "$status" = %s ]]; then exit 0; fi
  echo "Expected exit code %s, received $status" >&2
  [[ "$status" != 0 ]] || status=1
fi
exit "$status"
""" % (
        _quote(_runfile(ctx, host.directory)),
        _quote(host.entry_point),
        _quote(_runfile(ctx, runtime)),
        "\n".join(collection) or ":",
        "1" if test else "0",
        "1" if readonly else "0",
        _quote(assembly),
        _quote(ctx.attr.test_working_directory if test else ""),
        "\n".join(setup),
        'export CORE_ROOT="$native_host_root"' if host.launch_mode == "corerun" else "",
        "\n".join(outputs),
        host_environment,
        _quote(assembly),
        ctx.attr.expected_exit_code if test else 0,
        ctx.attr.expected_exit_code if test else 0,
    )
    write_shell_script(ctx, launcher, script)
    return ([RunEnvironmentInfo(environment = ctx.attr.env)] if test else []) + [DefaultInfo(
        executable = shell_launcher(ctx, launcher),
        files = depset([runtime]),
        runfiles = shell_runfiles(ctx, files = [launcher, runtime, host.directory] + [row.file for row in runtime_data.to_list()], transitive_files = host.files),
    )]

def create_test_protocol_launcher(ctx, tc, name, runtime, runtime_data, coverage_sources = {}):
    """Return the managed MTP/VSTest adapter and test environment.

    Args:
        ctx: Project rule context.
        tc: MSBuild toolchain.
        name: Assembly name.
        runtime: Compiled runtime output.
        runtime_data: Transitive data files.
        coverage_sources: Declared workspace source paths mapped to Bazel paths.

    Returns:
        The executable DefaultInfo and RunEnvironmentInfo providers.
    """
    if ctx.attr.test_protocol not in ["mtp", "vstest"]:
        fail("Managed test adapter requires the mtp or vstest protocol")
    test_tools = ([ctx.attr.test_runner] if ctx.attr.test_runner else []) + ctx.attr.test_adapters + ([ctx.attr.test_coverage_collector] if ctx.attr.test_coverage_collector else [])
    def_tool = None
    if ctx.attr.test_runner:
        def_tool = ctx.attr.test_runner[MSBuildTestToolInfo]
    host = _runtime_host(ctx)
    launch_request = ctx.actions.declare_file(ctx.label.name + ".launch.json")
    ctx.actions.write(launch_request, json.encode({
        "runtimeHost": {"directory": _runfile(ctx, host.directory), "entryPoint": host.entry_point, "launchMode": host.launch_mode, "runtimeIdentifier": host.runtime_identifier, "version": host.version, "environment": host.environment},
        "entry": _runfile(ctx, runtime),
        "assembly": name,
        "testOptions": {
            "protocol": ctx.attr.test_protocol,
            "coverage": ctx.attr.test_coverage,
            "coverageSources": coverage_sources if ctx.attr.test_coverage else {},
            "coverageCollector": _runfile(ctx, ctx.attr.test_coverage_collector[MSBuildTestToolInfo].directory) + "/" + ctx.attr.test_coverage_collector[MSBuildTestToolInfo].path if ctx.attr.test_coverage_collector else None,
            "settings": _runfile(ctx, ctx.file.test_settings) if ctx.file.test_settings else None,
            "settingsOutput": ctx.attr.test_settings_output or None,
            "filterArgument": ctx.attr.test_filter_argument,
            "allowEmpty": ctx.attr.allow_empty_tests,
            "diagnostics": ctx.attr.test_diagnostics,
            "outputDirectories": ctx.attr.test_output_dirs,
            "workingDirectory": ctx.attr.test_working_directory or None,
            "runner": _runfile(ctx, def_tool.directory) + "/" + def_tool.path if def_tool else None,
            "adapters": [_runfile(ctx, tool[MSBuildTestToolInfo].directory) + "/" + tool[MSBuildTestToolInfo].path for tool in ctx.attr.test_adapters],
        },
        "data": [{"source": _runfile(ctx, row.file), "path": row.destination} for row in runtime_data.to_list()],
    }))
    launcher = ctx.actions.declare_file(ctx.label.name)
    script = """#!/usr/bin/env bash
set -euo pipefail
export RULES_MSBUILD_RUNFILES="$runfiles_context"
resolve_runfile %s
dotnet="$RULES_MSBUILD_RESOLVED_RUNFILE"
resolve_runfile %s
runner="$RULES_MSBUILD_NATIVE_RUNFILE"
resolve_runfile %s
request="$RULES_MSBUILD_NATIVE_RUNFILE"
export DOTNET_ROOT="${dotnet%%/*}"
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) export DOTNET_ROOT="$(native_path "$DOTNET_ROOT")" ;; esac
exec "$dotnet" "$runner" test-protocol "$request" "$@"
""" % (_quote(_runfile(ctx, tc.dotnet)), _quote(_runfile(ctx, tc.runner)), _quote(_runfile(ctx, launch_request)))
    write_shell_script(ctx, launcher, script)
    runfiles = shell_runfiles(
        ctx,
        files = [launcher, tc.dotnet, tc.runner, runtime, launch_request] + [host.directory] + [row.file for row in runtime_data.to_list()] + ([ctx.file.test_settings] if ctx.file.test_settings else []),
        transitive_files = depset(transitive = [host.files] + [tc.runtime, tc.runner_support] + [tool[MSBuildTestToolInfo].files for tool in test_tools]),
    )
    return [RunEnvironmentInfo(environment = ctx.attr.env)] + [DefaultInfo(executable = shell_launcher(ctx, launcher), files = depset([runtime]), runfiles = runfiles)]
