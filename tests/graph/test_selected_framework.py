"""SDK-selected downstream multi-target framework discovery."""
import unittest
import test_export_graph as graph_tests


class SelectedReferenceFramework(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        graph_tests.GraphExportAcceptance.setUpClass.__func__(cls)

    setUp = graph_tests.GraphExportAcceptance.setUp
    tearDown = graph_tests.GraphExportAcceptance.tearDown
    restore = graph_tests.GraphExportAcceptance.restore
    export = graph_tests.GraphExportAcceptance.export

    def configure_multitargeted_dependency(self, frameworks):
        project = self.work / 'src/Shared/Shared.csproj'
        project.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework></TargetFramework><TargetFrameworks>' + frameworks + '</TargetFrameworks></PropertyGroup></Project>')
        return project

    def test_sdk_selects_inner_dependency_without_changing_declaration(self):
        project = self.configure_multitargeted_dependency('net10.0;netstandard2.1')
        declaration = project.read_bytes()
        self.restore()
        graph = self.export()
        nodes = {node['project']: node for node in graph['nodes']}
        self.assertEqual(len(nodes), 4)
        shared = nodes['workspace/src/Shared/Shared.csproj']
        self.assertEqual(shared['globalProperties']['targetframework'], 'net10.0')
        self.assertTrue(all(node['targetFramework'] == 'net10.0' for node in nodes.values()))
        for name in ('Left', 'Right'):
            self.assertEqual(nodes[f'workspace/src/{name}/{name}.csproj']['execution']['selectedReferences'],
                             [{'project': 'workspace/src/Shared/Shared.csproj', 'targetFramework': 'net10.0'}])
        self.assertEqual(project.read_bytes(), declaration)
        self.assertFalse(list(self.work.glob('src/**/bin/**/*.dll')))

    def test_netstandard_framework_identity_and_output_discovery(self):
        # Discovery-only fixture: package acquisition is tested by the Spectre
        # package/acceptance gate, independently of SDK framework negotiation.
        project = self.work / 'src/Shared/Shared.csproj'
        project.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFramework>netstandard2.0</TargetFramework>'
            '<DisableImplicitFrameworkReferences>true</DisableImplicitFrameworkReferences>'
            '</PropertyGroup></Project>')
        declaration = project.read_bytes()
        self.restore()
        nodes = {node['project']: node for node in self.export()['nodes']}
        shared = nodes['workspace/src/Shared/Shared.csproj']
        self.assertEqual(shared['targetFramework'], 'netstandard2.0')
        self.assertTrue(shared['execution']['outputDirectory'].endswith('/netstandard2.0'))
        for name in ('Left', 'Right'):
            # The SDK needs no SetTargetFramework override for a single-target
            # dependency; retaining that absence is part of ordinary semantics.
            self.assertEqual(nodes[f'workspace/src/{name}/{name}.csproj']['execution']['selectedReferences'], [])
            self.assertIn(shared['id'], nodes[f'workspace/src/{name}/{name}.csproj']['dependencies'])
            self.assertEqual(nodes[f'workspace/src/{name}/{name}.csproj']['targetFramework'], 'net10.0')
        self.assertEqual(project.read_bytes(), declaration)
        self.assertFalse(list(self.work.glob('src/**/bin/**/*.dll')))

    def test_unsupported_sdk_selection_still_rejects(self):
        self.configure_multitargeted_dependency('netstandard2.1;netstandard2.0')
        self.restore()
        self.export(error='unsupported-configuration')


if __name__ == '__main__': unittest.main()
