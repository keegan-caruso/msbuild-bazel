using Newtonsoft.Json;

namespace Catalog;

public static class CatalogStore
{
    public static string Revision() => "warehouse-v1";

    public static IReadOnlyList<Product> Read()
    {
        using var stream = typeof(CatalogStore).Assembly.GetManifestResourceStream("Data.products.json")
            ?? throw new InvalidOperationException("Missing catalog resource");
        using var reader = new StreamReader(stream);
        return JsonConvert.DeserializeObject<Product[]>(reader.ReadToEnd())
            ?? throw new InvalidOperationException("Invalid catalog resource");
    }
}
