using System.Text;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.Text;

namespace ClassicGenerator;

[Generator]
public sealed class ClassicValueGenerator : ISourceGenerator
{
    private static readonly DiagnosticDescriptor Sentinel = new(
        "GEN001",
        "Classic generator sentinel",
        "Classic generator observed sentinel input '{0}'",
        "GeneratorRoles",
        DiagnosticSeverity.Warning,
        isEnabledByDefault: true);

    public void Initialize(GeneratorInitializationContext context)
    {
    }

    public void Execute(GeneratorExecutionContext context)
    {
        context.AnalyzerConfigOptions.GlobalOptions.TryGetValue(
            "build_property.GeneratorPrefix", out var prefix);

        var values = new List<string>();
        var suffix = "missing-editor-option";
        var diagnosticLocation = context.Compilation.SyntaxTrees
            .OrderBy(tree => tree.FilePath, StringComparer.Ordinal)
            .First()
            .GetLocation(new TextSpan(0, 0));
        foreach (var input in context.AdditionalFiles.OrderBy(file => file.Path, StringComparer.Ordinal))
        {
            var name = Path.GetFileNameWithoutExtension(input.Path);
            var sourceText = input.GetText(context.CancellationToken);
            var value = sourceText?.ToString().Trim() ?? string.Empty;
            values.Add(name + "=" + value);
            if (context.AnalyzerConfigOptions.GetOptions(input).TryGetValue("r05_generator_suffix", out var configured))
            {
                suffix = configured;
            }
            if (name.Equals("sentinel", StringComparison.OrdinalIgnoreCase))
            {
                context.ReportDiagnostic(Diagnostic.Create(
                    Sentinel,
                    diagnosticLocation,
                    Path.GetFileName(input.Path)));
            }
        }

        var summary = string.Join("|", prefix ?? "missing-prefix", suffix, string.Join(",", values));
        var source = "namespace Generated; public static class ClassicGenerated { public const string Summary = "
            + SymbolDisplay.FormatLiteral(summary, quote: true) + "; }";
        context.AddSource("ClassicGenerated.g.cs", SourceText.From(source, Encoding.UTF8));
    }
}
