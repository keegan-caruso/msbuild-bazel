"""Shared helpers for generated Starlark extension validation."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests/graph"))

from prepare_graph import DOTNET_ROOT, prepare


BAZEL = Path(os.environ.get("SPIKE_BAZEL", ROOT / ".tools/bin/bazel"))


def configured_id(project, properties):
    """Compute the documented configured identity independently of a manifest."""
    normalized = {key.lower(): value for key, value in properties.items()}
    identity = project + "\n" + "\n".join(
        key + "=" + normalized[key] for key in sorted(normalized)
    )
    return hashlib.sha256(identity.encode()).hexdigest()[:24]


def action_graph_paths(container):
    fragments = {item["id"]: item for item in container.get("pathFragments", [])}
    cache = {}

    def path(identity):
        if identity in cache:
            return cache[identity]
        item = fragments[identity]
        parent = path(item["parentId"]) + "/" if item.get("parentId") else ""
        cache[identity] = parent + item["label"]
        return cache[identity]

    return {
        item["id"]: path(item["pathFragmentId"])
        for item in container.get("artifacts", [])
    }


def action_inputs(container, action):
    artifacts = action_graph_paths(container)
    sets = {item["id"]: item for item in container.get("depSetOfFiles", [])}
    cache = {}

    def expand(identity):
        if identity in cache:
            return cache[identity]
        item = sets[identity]
        result = {artifacts[value] for value in item.get("directArtifactIds", [])}
        for child in item.get("transitiveDepSetIds", []):
            result.update(expand(child))
        cache[identity] = result
        return result

    result = set()
    for identity in action.get("inputDepSetIds", []):
        result.update(expand(identity))
    return result


def action_outputs(container, action):
    artifacts = action_graph_paths(container)
    return {artifacts[identity] for identity in action.get("outputIds", [])}


def action_labels(container):
    return {item["id"]: item["label"] for item in container.get("targets", [])}


def actions_by_label(container, mnemonic):
    labels = action_labels(container)
    result = {}
    for action in container.get("actions", []):
        if action.get("mnemonic") != mnemonic:
            continue
        result[labels[action["targetId"]]] = action
    return result


class Harness:
    def __init__(self, prefix="starlark-extensions-"):
        self.evidence = Path(tempfile.mkdtemp(prefix=prefix)).resolve()
        self.env = dict(
            os.environ,
            DOTNET_CLI_HOME=str(self.evidence / "home"),
            NUGET_PACKAGES=str(self.evidence / "bootstrap-packages"),
            DOTNET_CLI_TELEMETRY_OPTOUT="1",
            DOTNET_NOLOGO="1",
            MSBUILDDISABLENODEREUSE="1",
        )
        self.serial = 0

    def fixture_environment(self, workspace):
        return dict(self.env, NUGET_PACKAGES=str(workspace / ".nuget/packages"))

    def run(self, name, arguments, cwd, success=True, timeout=600, environment=None):
        self.serial += 1
        result = subprocess.run(
            list(map(str, arguments)),
            cwd=cwd,
            env=environment or self.env,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        (self.evidence / f"{self.serial:03d}-{name}.log").write_text(
            result.stdout + result.stderr
        )
        if success and result.returncode:
            raise AssertionError(
                name + " failed:\n" + (result.stdout + result.stderr)[-12000:]
            )
        return result

    def build_exporter(self):
        self.run(
            "exporter-build",
            [DOTNET_ROOT / "dotnet", "build", ROOT / "tools/GraphExport", "-c", "Release", "--nologo", "-nodeReuse:false"],
            ROOT,
        )

    def export(self, workspace, name, entry="build.proj", properties=None):
        properties = properties or {"Configuration": "Release"}
        manifest = self.evidence / (name + "-graph.json")
        request = self.evidence / (name + "-request.json")
        request.write_text(json.dumps({
            "schemaVersion": 1,
            "workspace": str(workspace),
            "dotnetRoot": str(DOTNET_ROOT),
            "sdkVersion": "10.0.100",
            "packageRoot": str(workspace / ".nuget/packages"),
            "entryPoints": [{"project": entry, "globalProperties": properties}],
            "output": str(manifest),
        }))
        self.run(
            name + "-export",
            [
                DOTNET_ROOT / "dotnet",
                ROOT / "tools/GraphExport/bin/Release/net10.0/GraphExport.dll",
                "--request",
                request,
            ],
            workspace,
            environment=self.fixture_environment(workspace),
        )
        return manifest, json.loads(manifest.read_text())

    def restore(self, workspace, name, entry="build.proj", properties=None):
        properties = properties or {"Configuration": "Release"}
        package_root = workspace / ".nuget/packages"
        package_root.mkdir(parents=True, exist_ok=True)
        arguments = [
            DOTNET_ROOT / "dotnet",
            "msbuild",
            entry,
            "-t:Restore",
            *("-p:" + key + "=" + value for key, value in properties.items()),
            "-p:RestorePackagesPath=" + str(package_root),
            "-nodeReuse:false",
            "-nologo",
        ]
        self.run(
            name + "-restore",
            arguments,
            workspace,
            environment=self.fixture_environment(workspace),
        )

    def prepare(self, workspace, manifest, name, tests=None):
        output = self.evidence / (name + "-generated")
        graph = prepare(
            workspace,
            manifest,
            output,
            environment=self.fixture_environment(workspace),
            tests=tests,
        )
        self.run(name + "-format", [sys.executable, ROOT / "scripts/check-starlark.py", "--workspace", output], ROOT)
        return output, graph

    def bazel(self, generated, name, arguments):
        safe = "".join(character if character.isalnum() else "-" for character in name)
        result = self.run(
            name,
            [
                BAZEL,
                "--batch",
                "--nohome_rc",
                "--noworkspace_rc",
                "--output_user_root=" + str(self.evidence / "bazel-user"),
                "--output_base=" + str(self.evidence / ("bazel-base-" + safe)),
                *arguments,
                "--noshow_progress",
                "--color=no",
                "--curses=no",
            ],
            generated,
        )
        return result.stdout

    def aquery(self, generated, name, expression):
        return json.loads(self.bazel(
            generated,
            name,
            ["aquery", expression, "--output=jsonproto", "--include_file_write_contents"],
        ))

    def cquery_labels(self, generated, name, expression):
        return set(self.bazel(
            generated,
            name,
            ["cquery", expression, "--output=label"],
        ).splitlines())

    def copy_configured(self, name):
        workspace = self.evidence / (name + "-source")
        shutil.copytree(ROOT / "tests/fixtures/configured-nodes", workspace)
        return workspace

    def restore_configured(self, workspace, name):
        self.restore(workspace, name)
        for flavor in ("red", "blue"):
            self.restore(
                workspace,
                name + "-" + flavor,
                entry="Shared/Shared.csproj",
                properties={"Configuration": "Release", "Flavor": flavor},
            )
