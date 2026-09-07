using System.Collections.Immutable;
using System.Text;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.Text;

namespace IncrementalGenerator;

[Generator]
public sealed class IncrementalValueGenerator : IIncrementalGenerator
{
    private static readonly DiagnosticDescriptor Sentinel = new(
        "GEN002",
        "Incremental generator sentinel",
        "Incremental generator observed sentinel input '{0}'",
        "GeneratorRoles",
        DiagnosticSeverity.Warning,
        isEnabledByDefault: true);

    public void Initialize(IncrementalGeneratorInitializationContext context)
    {
        var prefix = context.AnalyzerConfigOptionsProvider.Select(static (options, _) =>
            options.GlobalOptions.TryGetValue("build_property.GeneratorPrefix", out var value)
                ? value
                : "missing-prefix");
        var inputs = context.AdditionalTextsProvider
            .Combine(context.AnalyzerConfigOptionsProvider)
            .Select(static (pair, cancellationToken) =>
            {
                var text = pair.Left;
                var name = Path.GetFileNameWithoutExtension(text.Path);
                var value = text.GetText(cancellationToken)?.ToString().Trim() ?? string.Empty;
                var suffix = pair.Right.GetOptions(text).TryGetValue("r05_generator_suffix", out var configured)
                    ? configured
                    : "missing-editor-option";
                return new Input(text.Path, name, value, suffix);
            });

        context.RegisterSourceOutput(
            inputs.Collect().Combine(prefix).Combine(context.CompilationProvider),
            static (production, pair) =>
        {
            var sorted = pair.Left.Left.OrderBy(input => input.Name, StringComparer.Ordinal).ToImmutableArray();
            var diagnosticLocation = pair.Right.SyntaxTrees
                .OrderBy(tree => tree.FilePath, StringComparer.Ordinal)
                .First()
                .GetLocation(new TextSpan(0, 0));
            foreach (var input in sorted.Where(input => input.Name.Equals("sentinel", StringComparison.OrdinalIgnoreCase)))
            {
                production.ReportDiagnostic(Diagnostic.Create(
                    Sentinel,
                    diagnosticLocation,
                    input.Name + ".txt"));
            }
            var suffix = sorted.IsDefaultOrEmpty ? "missing-editor-option" : sorted[0].Suffix;
            var values = string.Join(",", sorted.Select(input => input.Name + "=" + input.Value));
            var summary = string.Join("|", pair.Left.Right, suffix, values);
            var source = "namespace Generated; public static class IncrementalGenerated { public const string Summary = "
                + SymbolDisplay.FormatLiteral(summary, quote: true) + "; }";
            production.AddSource("IncrementalGenerated.g.cs", SourceText.From(source, Encoding.UTF8));
        });
    }

    private readonly record struct Input(string Path, string Name, string Value, string Suffix);
}
