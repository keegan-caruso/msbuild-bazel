using System.Collections;
using Microsoft.Build.Framework;
using Microsoft.Build.Utilities;

namespace RulesMSBuild.GraphBuild;

internal sealed class CachedTargetItem(string include) : ITaskItem2
{
    private readonly ITaskItem2 item = new TaskItem(include);
    public string ItemSpec
    {
        get => item.ItemSpec;
        set => item.ItemSpec = value;
    }
    public string EvaluatedIncludeEscaped
    {
        get => item.EvaluatedIncludeEscaped;
        set => item.EvaluatedIncludeEscaped = value;
    }
    public ICollection MetadataNames => item.MetadataNames;
    public int MetadataCount => item.MetadataCount;
    public string GetMetadata(string name) => item.GetMetadata(name);
    public void SetMetadata(string name, string value) => item.SetMetadata(name, value);
    public void RemoveMetadata(string name) => item.RemoveMetadata(name);
    public IDictionary CloneCustomMetadata() => item.CloneCustomMetadata();
    public string GetMetadataValueEscaped(string name) => item.GetMetadataValueEscaped(name);
    public void SetMetadataValueLiteral(string name, string value) => item.SetMetadataValueLiteral(name, value);
    public IDictionary CloneCustomMetadataEscaped() => item.CloneCustomMetadataEscaped();
    void ITaskItem.CopyMetadataTo(ITaskItem destinationItem)
    {
        var destinationOriginal = destinationItem.GetMetadata("OriginalItemSpec");
        var sourceOriginal = GetMetadata("OriginalItemSpec");
        item.CopyMetadataTo(destinationItem);
        // The project-cache adapter copies into a fresh engine item. TaskItem's
        // magic OriginalItemSpec would replace the saved source identity with
        // our rebased Include. Preserve declared metadata while respecting an
        // existing destination value, as for every other copied metadatum.
        if (destinationOriginal.Length == 0 && sourceOriginal.Length != 0)
        {
            if (destinationItem is ITaskItem2 literalItem)
            {
                literalItem.SetMetadataValueLiteral("OriginalItemSpec", sourceOriginal);
            }
            else
            {
                destinationItem.SetMetadata("OriginalItemSpec", Microsoft.Build.Evaluation.ProjectCollection.Escape(sourceOriginal));
            }
        }
    }
}
