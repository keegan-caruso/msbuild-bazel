"""Native Windows entry points for generated Bash launchers."""

load(":paths.bzl", "runfile")

SHELL_TOOLCHAIN = Label("@rules_shell//shell:toolchain_type")

def shell_launcher_attrs():
    return {
        "_launcher_windows_constraint": attr.label(default = Label("@platforms//os:windows")),
        "_shell_runfiles_dep": attr.label(default = Label("@rules_shell//shell/runfiles")),
    }

def shell_launcher(ctx, script):
    """Return the original script or a Windows PE launcher for its runfile.

    The shell toolchain owns the interpreter and generic launcher binaries.
    Callers include the script in their runfiles alongside the returned executable.

    Args:
        ctx: Rule context with shell launcher attributes and toolchain resolution.
        script: Declared generated Bash script.

    Returns:
        The original script or its declared Windows executable launcher.
    """
    if not ctx.target_platform_has_constraint(ctx.attr._launcher_windows_constraint[platform_common.ConstraintValueInfo]):
        return script
    shell = ctx.toolchains[SHELL_TOOLCHAIN]
    if not shell or not shell.path or not shell.launcher or not shell.launcher_maker:
        fail("Windows MSBuild launchers require a shell toolchain with Bash, launcher, and launcher_maker; set BAZEL_SH to bash.exe on Windows")
    executable = ctx.actions.declare_file(ctx.label.name + ".exe")
    info = ctx.actions.args()
    info.use_param_file("%s", use_always = True)
    info.set_param_file_format("multiline")
    info.add("binary_type=Bash")
    info.add(ctx.workspace_name, format = "workspace_name=%s")

    # Prefer the manifest; Bazel's launcher falls back to RUNFILES_DIR when absent.
    info.add("symlink_runfiles_enabled=0")
    info.add(shell.path, format = "bash_bin_path=%s")
    info.add(runfile(ctx, script), format = "bash_file_rlocationpath=%s")
    ctx.actions.run(
        executable = shell.launcher_maker,
        inputs = [shell.launcher],
        outputs = [executable],
        arguments = [shell.launcher.path, info, executable.path],
        use_default_shell_env = True,
        toolchain = SHELL_TOOLCHAIN,
        mnemonic = "MSBuildShellLauncher",
    )
    return executable

def shell_runfiles(ctx, files = [], transitive_files = None):
    return ctx.runfiles(files = files, transitive_files = transitive_files).merge(ctx.attr._shell_runfiles_dep[DefaultInfo].default_runfiles)

def write_shell_script(ctx, output, script):
    """Initialize the pinned runfiles library before the generated script body."""
    ctx.actions.write(output, "#!/usr/bin/env bash\n" + _shell_prelude() + script.removeprefix("#!/usr/bin/env bash\n"), is_executable = True)

def _shell_prelude():
    return """set -uo pipefail
set +e
if [[ -z "${RUNFILES_DIR:-}" && -n "${TEST_SRCDIR:-}" ]]; then export RUNFILES_DIR="$TEST_SRCDIR"; fi
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
        export MSYS2_ARG_CONV_EXCL='*'
        if [[ -n "${RUNFILES_DIR:-}" ]]; then export RUNFILES_DIR="$(cygpath -au "$RUNFILES_DIR")"; fi
        if [[ -n "${RUNFILES_MANIFEST_FILE:-}" ]]; then export RUNFILES_MANIFEST_FILE="$(cygpath -au "$RUNFILES_MANIFEST_FILE")"; fi
        ;;
esac
if [[ -n "${RUNFILES_DIR:-}" && "$RUNFILES_DIR" != /* ]]; then export RUNFILES_DIR="$PWD/$RUNFILES_DIR"; fi
if [[ -n "${RUNFILES_MANIFEST_FILE:-}" && "$RUNFILES_MANIFEST_FILE" != /* ]]; then export RUNFILES_MANIFEST_FILE="$PWD/$RUNFILES_MANIFEST_FILE"; fi
_rules_msbuild_library_key=bazel_tools/tools/bash/runfiles/runfiles.bash
_rules_msbuild_source_manifest_library() {
    [[ -f "$1" ]] || return 1
    local row value
    while IFS= read -r row || [[ -n "$row" ]]; do
        if [[ "$row" == "$_rules_msbuild_library_key "* ]]; then
            value="${row#"$_rules_msbuild_library_key "}"
        elif [[ "$row" == " $_rules_msbuild_library_key "* ]]; then
            value="${row#" $_rules_msbuild_library_key "}"
            value="${value//\\\\s/ }"
            value="${value//\\\\n/$'\\n'}"
            value="${value//\\\\b/\\\\}"
        else
            continue
        fi
        [[ -f "$value" ]] || return 1
        case "$(uname -s)" in
            MINGW*|MSYS*|CYGWIN*) RUNFILES_MANIFEST_FILE="$(cygpath -au "$1")" ;;
            *)
                RUNFILES_MANIFEST_FILE="$1"
                [[ "$RUNFILES_MANIFEST_FILE" = /* ]] || RUNFILES_MANIFEST_FILE="$PWD/$RUNFILES_MANIFEST_FILE"
                ;;
        esac
        export RUNFILES_MANIFEST_FILE RUNFILES_MANIFEST_ONLY=1
        source "$value"
        return
    done < "$1"
    return 1
}
source "${RUNFILES_DIR:-/dev/null}/$_rules_msbuild_library_key" 2>/dev/null ||
_rules_msbuild_source_manifest_library "${RUNFILES_MANIFEST_FILE:-/dev/null}" 2>/dev/null ||
source "$0.runfiles/$_rules_msbuild_library_key" 2>/dev/null ||
_rules_msbuild_source_manifest_library "$0.runfiles_manifest" 2>/dev/null ||
_rules_msbuild_source_manifest_library "$0.exe.runfiles_manifest" 2>/dev/null ||
{ echo 'msbuild launcher: cannot find the declared runfiles library' >&2; exit 1; }
unset -f _rules_msbuild_source_manifest_library
unset _rules_msbuild_library_key
set -e
runfiles_export_envvars
native_path() {
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) cygpath -am "$1" ;;
        *) printf '%s\\n' "$1" ;;
    esac
}
resolve_runfile() {
    # Preserve trailing newline characters in Unix filenames across command substitution.
    RULES_MSBUILD_RESOLVED_RUNFILE="$(rlocation "$1" '' && printf x)" || return
    RULES_MSBUILD_RESOLVED_RUNFILE="${RULES_MSBUILD_RESOLVED_RUNFILE%x}"
    RULES_MSBUILD_RESOLVED_RUNFILE="${RULES_MSBUILD_RESOLVED_RUNFILE%$'\\n'}"
    [[ -n "$RULES_MSBUILD_RESOLVED_RUNFILE" ]] || { echo "msbuild launcher: missing runfile: $1" >&2; return 1; }
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) ;;
        *) [[ "$RULES_MSBUILD_RESOLVED_RUNFILE" = /* ]] || RULES_MSBUILD_RESOLVED_RUNFILE="$PWD/$RULES_MSBUILD_RESOLVED_RUNFILE" ;;
    esac
    RULES_MSBUILD_NATIVE_RUNFILE="$RULES_MSBUILD_RESOLVED_RUNFILE"
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*)
            RULES_MSBUILD_NATIVE_RUNFILE="$(cygpath -am "$RULES_MSBUILD_RESOLVED_RUNFILE")"
            RULES_MSBUILD_RESOLVED_RUNFILE="$(cygpath -au "$RULES_MSBUILD_RESOLVED_RUNFILE")"
            ;;
    esac
}
if [[ "${RUNFILES_MANIFEST_ONLY:-0}" = 1 && -f "${RUNFILES_MANIFEST_FILE:-/dev/null}" ]]; then
    runfiles_context="$RUNFILES_MANIFEST_FILE"
elif [[ -d "${RUNFILES_DIR:-/dev/null}" ]]; then
    runfiles_context="$RUNFILES_DIR"
elif [[ -f "${RUNFILES_MANIFEST_FILE:-/dev/null}" ]]; then
    runfiles_context="$RUNFILES_MANIFEST_FILE"
else
    echo 'msbuild launcher: missing runfiles directory or manifest' >&2
    exit 1
fi
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) runfiles_context="$(native_path "$runfiles_context")" ;; esac
"""
