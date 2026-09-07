using System.Collections.Immutable;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Diagnostics;

namespace DiagnosticAnalyzer;

[DiagnosticAnalyzer(LanguageNames.CSharp)]
public sealed class MarkerAnalyzer : Microsoft.CodeAnalysis.Diagnostics.DiagnosticAnalyzer
{
    private static readonly DiagnosticDescriptor Rule = new(
        "ROLE001", "Marker declaration", "Marker declaration observed: {0}",
        "ReferenceRoles", DiagnosticSeverity.Warning, isEnabledByDefault: true);

    public override ImmutableArray<DiagnosticDescriptor> SupportedDiagnostics => [Rule];

    public override void Initialize(AnalysisContext context)
    {
        context.ConfigureGeneratedCodeAnalysis(GeneratedCodeAnalysisFlags.None);
        context.EnableConcurrentExecution();
        context.RegisterSyntaxNodeAction(node =>
        {
            var declaration = (ClassDeclarationSyntax)node.Node;
            if (declaration.Identifier.ValueText == "DiagnosticMarker")
                node.ReportDiagnostic(Diagnostic.Create(Rule, declaration.Identifier.GetLocation(), "v1"));
        }, SyntaxKind.ClassDeclaration);
    }
}
