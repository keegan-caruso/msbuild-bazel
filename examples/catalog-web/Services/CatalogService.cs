using Humanizer;

namespace Catalog;

public sealed class CatalogService
{
    public IReadOnlyList<Product> All() => CatalogStore.Read()
        .Select(product => product with { Name = product.Name.Humanize(LetterCasing.Title) }).ToArray();

    public string Revision() => CatalogStore.Revision();
}
