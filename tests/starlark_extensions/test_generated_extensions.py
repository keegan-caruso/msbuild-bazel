"""S04 generated-workspace validation for the selected R02-R04 slices."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests/graph"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from binary_inputs import Packages
from graph_private_assets import configure, write_fixture
from prepare_graph import prepare, write_build
from support import (
    DOTNET_ROOT,
    Harness,
    action_inputs,
    action_outputs,
    actions_by_label,
    configured_id,
)


PACKAGE_IDENTITIES = {
    "1.0.0": {"RulesMsbuild.Binary/1.0.0", "RulesMsbuild.Leaf/1.0.0"},
    "1.0.1": {"RulesMsbuild.Binary/1.0.1", "RulesMsbuild.Leaf/1.0.0"},
}


def package_files(version):
    result = set()
    for identity in PACKAGE_IDENTITIES[version]:
        package, selected = identity.split("/")
        root = "packages/" + package.lower() + "/" + selected + "/"
        result.update({
            root + package.lower() + ".nuspec",
            root + "ref/net10.0/" + package + ".dll",
            root + "lib/net10.0/" + package + ".dll",
            root + package.lower() + "." + selected + ".nupkg.sha512",
        })
    return result


class GeneratedExtensionValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness = Harness()
        print("Generated extension evidence: " + str(cls.harness.evidence), file=sys.stderr)
        cls.harness.build_exporter()
        cls.packages = Packages(
            cls.harness.evidence / "binary-package-build",
            DOTNET_ROOT / "dotnet",
            lambda name, command, cwd: cls.harness.run(name, command, cwd),
        )

    def package_plan(self, name, version, private_assets):
        workspace = self.harness.evidence / (name + "-source")
        write_fixture(workspace)
        self.packages.feed(workspace / ".feed")
        configure(workspace, workspace / ".feed", version=version, private_assets=private_assets)
        self.harness.restore(workspace, name)
        manifest, _ = self.harness.export(workspace, name)
        generated, graph = self.harness.prepare(workspace, manifest, name)
        return workspace, generated, graph

    def package_actions(self, generated, graph, name):
        container = self.harness.aquery(
            generated,
            name,
            "mnemonic(MsbuildProject, deps(//:all))",
        )
        by_label = actions_by_label(container, "MsbuildProject")
        expected_labels = {"//:node_" + node["id"] for node in graph["nodes"]}
        self.assertEqual(set(by_label), expected_labels)
        return {
            Path(node["project"]).stem: (node, action_inputs(container, by_label["//:node_" + node["id"]]))
            for node in graph["nodes"]
        }

    def assert_package_plan(self, generated, graph, name, version, app_has_packages):
        actions = self.package_actions(generated, graph, name)
        ids = {project: node["id"] for project, (node, _) in actions.items()}
        dependencies = {
            "Shared": set(),
            "Left": {"Shared"},
            "Right": {"Shared"},
            "App": {"Left", "Right", "Shared"},
        }
        ownership = {
            "Shared": set(),
            "Left": package_files(version),
            "Right": set(),
            "App": package_files(version) if app_has_packages else set(),
        }
        identities = {
            "Shared": set(),
            "Left": PACKAGE_IDENTITIES[version],
            "Right": set(),
            "App": PACKAGE_IDENTITIES[version] if app_has_packages else set(),
        }
        for project, (node, inputs) in actions.items():
            with self.subTest(plan=name, project=project):
                actual_packages = {path for path in inputs if path.startswith("packages/")}
                self.assertEqual(actual_packages, ownership[project])
                actual_restore = {path for path in inputs if path.startswith("restore/")}
                expected_restore = {"restore/" + ids[item] + ".json" for item in dependencies[project] | {project}}
                self.assertEqual(actual_restore, expected_restore)
                manifests = {path for path in inputs if path.startswith("package-manifests/")}
                self.assertEqual(manifests, {"package-manifests/" + node["id"] + ".json"})
                payload = json.loads((generated / next(iter(manifests))).read_text())
                actual_identities = {item["id"] + "/" + item["version"] for item in payload["packages"]}
                self.assertEqual(actual_identities, identities[project])
                for identity in identities[project]:
                    package, selected = identity.split("/")
                    root = "packages/" + package.lower() + "/" + selected
                    reference = generated / root / "ref/net10.0" / (package + ".dll")
                    runtime = generated / root / "lib/net10.0" / (package + ".dll")
                    self.assertIn(reference.relative_to(generated).as_posix(), inputs)
                    self.assertIn(runtime.relative_to(generated).as_posix(), inputs)
                    self.assertNotEqual(reference.read_bytes(), runtime.read_bytes())

    def test_r02_generated_package_closure_private_assets_and_upgrade(self):
        _, generated_all, graph_all = self.package_plan("packages-all-v1", "1.0.0", "all")
        self.assert_package_plan(
            generated_all,
            graph_all,
            "packages-all-v1-actions",
            "1.0.0",
            app_has_packages=False,
        )

        _, generated_v1, graph_v1 = self.package_plan("packages-none-v1", "1.0.0", "none")
        self.assert_package_plan(
            generated_v1,
            graph_v1,
            "packages-none-v1-actions",
            "1.0.0",
            app_has_packages=True,
        )
        _, generated_v2, graph_v2 = self.package_plan("packages-none-v2", "1.0.1", "none")
        self.assert_package_plan(
            generated_v2,
            graph_v2,
            "packages-none-v2-actions",
            "1.0.1",
            app_has_packages=True,
        )
        self.assertEqual(
            {node["id"]: node["project"] for node in graph_v1["nodes"]},
            {node["id"]: node["project"] for node in graph_v2["nodes"]},
        )
        for project in ("Shared", "Right"):
            v1 = next(node for node in graph_v1["nodes"] if Path(node["project"]).stem == project)
            v2 = next(node for node in graph_v2["nodes"] if Path(node["project"]).stem == project)
            self.assertEqual(v1["inputs"], v2["inputs"])

    def configured_plan(self, name, mutate=None):
        workspace = self.harness.copy_configured(name)
        props = workspace / "Directory.Build.props"
        props.write_text(props.read_text().replace(
            "</Project>",
            '<Import Project="Optional.props" Condition="Exists(\'Optional.props\')"/></Project>',
        ))
        if mutate:
            mutate(workspace)
        self.harness.restore_configured(workspace, name)
        manifest, graph = self.harness.export(workspace, name)
        generated, prepared = self.harness.prepare(workspace, manifest, name)
        self.assertEqual(graph, prepared)
        return workspace, manifest, generated, graph

    @staticmethod
    def expected_configured(edge="blue"):
        properties = {
            "App": ("workspace/App/App.csproj", {"configuration": "Release"}),
            "Left": ("workspace/Left/Left.csproj", {"configuration": "Release"}),
            "Right": ("workspace/Right/Right.csproj", {"configuration": "Release"}),
            "SharedRed": ("workspace/Shared/Shared.csproj", {"configuration": "Release", "flavor": "red"}),
            "Common": ("workspace/Common/Common.csproj", {"configuration": "Release"}),
        }
        if edge == "blue":
            properties["SharedBlue"] = (
                "workspace/Shared/Shared.csproj",
                {"configuration": "Release", "flavor": "blue"},
            )
        return {
            name: configured_id(project, props)
            for name, (project, props) in properties.items()
        }

    def assert_configured_analysis(self, generated, graph, name, edge="blue"):
        expected_ids = self.expected_configured(edge)
        self.assertEqual({node["id"] for node in graph["nodes"]}, set(expected_ids.values()))
        by_id = {node["id"]: node for node in graph["nodes"]}
        red = by_id[expected_ids["SharedRed"]]
        self.assertEqual(red["execution"]["outputDirectory"], "workspace/Shared/bin/red/Release/net10.0")
        self.assertEqual(red["execution"]["referenceDirectory"], "workspace/Shared/obj/red/Release/net10.0/ref")
        if edge == "blue":
            blue = by_id[expected_ids["SharedBlue"]]
            self.assertEqual(blue["execution"]["outputDirectory"], "workspace/Shared/bin/blue/Release/net10.0")
            self.assertEqual(blue["execution"]["referenceDirectory"], "workspace/Shared/obj/blue/Release/net10.0/ref")

        direct = {
            "Common": set(),
            "SharedRed": {"Common"},
            "Left": {"SharedRed"},
            "Right": {"SharedBlue" if edge == "blue" else "SharedRed"},
            "App": {"Left", "Right"},
        }
        if edge == "blue":
            direct["SharedBlue"] = {"Common"}
        reachable = {}

        def closure(node):
            if node not in reachable:
                reachable[node] = set(direct[node])
                for dependency in direct[node]:
                    reachable[node].update(closure(dependency))
            return reachable[node]

        for logical, identity in expected_ids.items():
            labels = self.harness.cquery_labels(
                generated,
                name + "-edges-" + logical,
                "deps(//:node_" + identity + ", 1)",
            )
            observed = {
                label.removeprefix("//:node_").split()[0]
                for label in labels
                if label.startswith("//:node_")
            }
            self.assertEqual(observed, {identity} | {expected_ids[value] for value in direct[logical]})

        container = self.harness.aquery(
            generated,
            name + "-actions",
            "mnemonic(MsbuildProject, deps(//:all))",
        )
        actions = actions_by_label(container, "MsbuildProject")
        self.assertEqual(set(actions), {"//:node_" + identity for identity in expected_ids.values()})
        for logical, identity in expected_ids.items():
            action = actions["//:node_" + identity]
            inputs = action_inputs(container, action)
            bundles = {
                Path(path).name.removeprefix("node_").removesuffix(".bundle")
                for path in inputs
                if path.endswith(".bundle")
            }
            self.assertEqual(bundles, {expected_ids[value] for value in closure(logical)})
            self.assertFalse(any(path.endswith(".diagnostics") for path in inputs))
        return container

    def test_r03_configured_identities_edges_closures_and_discovery_refresh(self):
        workspace, _, generated, graph = self.configured_plan("configured-baseline")
        baseline = self.assert_configured_analysis(generated, graph, "configured-baseline", edge="blue")
        baseline_inputs = set().union(*(
            action_inputs(baseline, action)
            for action in actions_by_label(baseline, "MsbuildProject").values()
        ))
        self.assertFalse(any(path.endswith("Optional.props") or path.endswith("Added.cs") for path in baseline_inputs))

        def mutate(source):
            right = source / "Right/Right.csproj"
            right.write_text(right.read_text().replace("Flavor=blue", "Flavor=red"))
            (source / "Optional.props").write_text(
                "<Project><PropertyGroup><OptionalInput>present</OptionalInput></PropertyGroup></Project>\n"
            )
            (source / "Shared/Added.cs").write_text("namespace Shared; internal static class Added {}\n")

        _, _, refreshed, changed = self.configured_plan("configured-refreshed", mutate=mutate)
        updated = self.assert_configured_analysis(refreshed, changed, "configured-refreshed", edge="red")
        updated_inputs = set().union(*(
            action_inputs(updated, action)
            for action in actions_by_label(updated, "MsbuildProject").values()
        ))
        self.assertTrue(any(path.endswith("src/Optional.props") for path in updated_inputs), sorted(updated_inputs))
        self.assertTrue(any(path.endswith("src/Shared/Added.cs") for path in updated_inputs), sorted(updated_inputs))
        self.assertEqual(
            {node["id"] for node in changed["nodes"]},
            set(self.expected_configured("red").values()),
        )
        self.assertTrue(workspace.is_dir())

    def test_r03_deterministic_generation_across_order_and_relocation(self):
        workspace, _, generated, graph = self.configured_plan("configured-deterministic")
        expected = self.expected_configured("blue")
        self.assertEqual({node["id"] for node in graph["nodes"]}, set(expected.values()))
        original_build = (generated / "BUILD.bazel").read_bytes()

        reordered = copy.deepcopy(graph)
        reordered["nodes"].reverse()
        reordered["entryPoints"].reverse()
        reordered["graphInputs"].reverse()
        for node in reordered["nodes"]:
            node["dependencies"].reverse()
            node["inputs"].reverse()
        order_output = self.harness.evidence / "configured-order-generated"
        (order_output / "restore").mkdir(parents=True)
        write_build(workspace, reordered, order_output)
        self.assertEqual((order_output / "BUILD.bazel").read_bytes(), original_build)

        relocated = self.harness.copy_configured("configured-relocated")
        props = relocated / "Directory.Build.props"
        props.write_text(props.read_text().replace(
            "</Project>",
            '<Import Project="Optional.props" Condition="Exists(\'Optional.props\')"/></Project>',
        ))
        self.harness.restore_configured(relocated, "configured-relocated")
        moved_manifest, moved_graph = self.harness.export(relocated, "configured-relocated")
        moved_generated, moved_prepared = self.harness.prepare(relocated, moved_manifest, "configured-relocated")
        self.assertEqual(moved_graph, graph)
        self.assertEqual(moved_prepared, graph)
        self.assertEqual((moved_generated / "BUILD.bazel").read_bytes(), original_build)
        self.assertNotIn(str(workspace), json.dumps(graph))
        self.assertNotIn(str(relocated), json.dumps(moved_graph))

    def make_test_plan(self, name, data):
        workspace = self.harness.evidence / (name + "-source")
        write_fixture(workspace)
        data_path = workspace / "test-data/approved.txt"
        data_path.parent.mkdir(parents=True)
        data_path.write_text(data)
        self.harness.restore(workspace, name)
        manifest, graph = self.harness.export(workspace, name)
        app = next(node for node in graph["nodes"] if node["project"] == "workspace/src/App/App.csproj")
        declarations = [{
            "node": app["id"],
            "data": ["test-data/approved.txt"],
            "expectedTests": ["Fixture.App.Approval"],
        }]
        generated, prepared = self.harness.prepare(workspace, manifest, name, tests=declarations)
        return workspace, manifest, generated, prepared, app

    def assert_test_actions(self, generated, app, name):
        target = "//:test_" + app["id"]
        labels = self.harness.cquery_labels(generated, name + "-load", target)
        self.assertTrue(any(label.split()[0] == target for label in labels), labels)
        container = self.harness.aquery(generated, name + "-actions", "deps(" + target + ")")
        tests = actions_by_label(container, "TestRunner")
        self.assertEqual(set(tests), {target})
        action = tests[target]
        inputs = action_inputs(container, action)
        policy = {item["key"]: item["value"] for item in action.get("executionInfo", [])}
        self.assertEqual(policy, {"no-remote": "1"})
        middleman_paths = {path for path in inputs if path.endswith(".sh-runfiles")}
        self.assertEqual(len(middleman_paths), 1)
        middlemen = [
            candidate
            for candidate in container.get("actions", [])
            if candidate.get("mnemonic") == "Middleman"
            and action_outputs(container, candidate) == middleman_paths
        ]
        self.assertEqual(len(middlemen), 1)
        runfiles = action_inputs(container, middlemen[0])
        self.assertTrue(
            any(path.endswith("test-data/test-data/approved.txt") for path in runfiles),
            sorted(runfiles),
        )
        for suffix in (".dll", ".deps.json", ".runtimeconfig.json"):
            self.assertTrue(any(path.endswith("test-runner/TestRunner" + suffix) for path in runfiles))
        self.assertTrue(any(path.endswith("host-identity.json") for path in runfiles))
        bundles = {Path(path).name for path in runfiles if path.endswith(".bundle")}
        self.assertEqual(len(bundles), 4)
        self.assertIn("node_" + app["id"] + ".bundle", bundles)
        requests = [
            candidate
            for candidate in container.get("actions", [])
            if candidate.get("mnemonic") == "FileWrite"
            and any(path.endswith("test_" + app["id"] + ".request.json") for path in action_outputs(container, candidate))
        ]
        self.assertEqual(len(requests), 1)
        contents = requests[0]["fileContents"]
        try:
            request = json.loads(contents)
        except json.JSONDecodeError:
            request = json.loads(base64.b64decode(contents))
        self.assertEqual(request["project"], "src/App/App.csproj")
        self.assertEqual(request["globalProperties"], {"configuration": "Release"})
        self.assertEqual(request["runtimeDirectory"], "src/App/bin/Release/net10.0")
        self.assertEqual(request["assembly"], "App.dll")
        self.assertEqual(request["expectedTests"], ["Fixture.App.Approval"])
        self.assertEqual(request["sourceRoot"], "/_/workspace")
        self.assertEqual(request["testData"][0]["destination"], "test-data/approved.txt")
        return container, action, request, requests[0]

    def test_r04_generated_test_target_runfiles_request_and_data_key(self):
        _, _, first, _, app = self.make_test_plan("test-data-first", "approved-v1\n")
        first_graph, first_action, first_request, first_write = self.assert_test_actions(
            first,
            app,
            "test-data-first",
        )
        manifest = json.loads((first / "tests.json").read_text())
        expected_hash = hashlib.sha256(b"approved-v1\n").hexdigest()
        self.assertEqual(manifest["tests"], [{
            "node": app["id"],
            "target": "//:test_" + app["id"],
            "dataHashes": {"test-data/approved.txt": expected_hash},
            "expectedTests": ["Fixture.App.Approval"],
        }])

        _, _, second, _, second_app = self.make_test_plan("test-data-second", "approved-v2\n")
        self.assertEqual(second_app["id"], app["id"])
        second_graph, second_action, second_request, second_write = self.assert_test_actions(
            second,
            second_app,
            "test-data-second",
        )
        first_data = first_request["testData"][0]
        second_data = second_request["testData"][0]
        self.assertEqual(
            {key: value for key, value in first_data.items() if key != "sha256"},
            {key: value for key, value in second_data.items() if key != "sha256"},
        )
        self.assertNotEqual(first_data["sha256"], second_data["sha256"])
        self.assertEqual(
            {key: value for key, value in first_request.items() if key != "testData"},
            {key: value for key, value in second_request.items() if key != "testData"},
        )
        self.assertEqual(action_inputs(first_graph, first_action), action_inputs(second_graph, second_action))
        self.assertNotEqual(first_write.get("actionKey"), second_write.get("actionKey"))
        first_builds = {
            label: (action.get("actionKey"), action_inputs(first_graph, action))
            for label, action in actions_by_label(first_graph, "MsbuildProject").items()
        }
        second_builds = {
            label: (action.get("actionKey"), action_inputs(second_graph, action))
            for label, action in actions_by_label(second_graph, "MsbuildProject").items()
        }
        self.assertEqual(first_builds, second_builds)
        self.assertNotEqual(
            (first / "test-data/test-data/approved.txt").read_bytes(),
            (second / "test-data/test-data/approved.txt").read_bytes(),
        )

    def test_r04_missing_test_data_rejects_without_publishing_plan(self):
        workspace = self.harness.evidence / "test-missing-source"
        write_fixture(workspace)
        self.harness.restore(workspace, "test-missing")
        manifest, graph = self.harness.export(workspace, "test-missing")
        app = next(node for node in graph["nodes"] if node["project"] == "workspace/src/App/App.csproj")
        output = self.harness.evidence / "test-missing-generated"
        with self.assertRaisesRegex(ValueError, "missing or escaping test data"):
            prepare(
                workspace,
                manifest,
                output,
                environment=self.harness.fixture_environment(workspace),
                tests=[{
                    "node": app["id"],
                    "data": ["test-data/missing.txt"],
                    "expectedTests": ["Fixture.App.Approval"],
                }],
            )
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
