using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text.Json;
using Catalog;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;

var smoke = args.Contains("--smoke", StringComparer.Ordinal);
var builder = WebApplication.CreateBuilder(new WebApplicationOptions
{
    Args = args.Where(value => value != "--smoke").ToArray(),
    ContentRootPath = AppContext.BaseDirectory,
});
if (smoke) builder.WebHost.UseUrls("http://127.0.0.1:0");
builder.Services.AddRazorPages();
builder.Services.AddSingleton<CatalogService>();
await using var app = builder.Build();
app.MapStaticAssets();
app.MapRazorPages();
app.MapGet("/api/products", (CatalogService catalog) => new { revision = catalog.Revision(), products = catalog.All() });
if (!smoke)
{
    await app.RunAsync();
    return;
}
await app.StartAsync();
try
{
    var address = app.Services.GetRequiredService<IServer>().Features.Get<IServerAddressesFeature>()!.Addresses.Single();
    using var client = new HttpClient { BaseAddress = new Uri(address), Timeout = TimeSpan.FromSeconds(10) };
    using var response = JsonDocument.Parse(await client.GetStringAsync("/api/products"));
    var revision = response.RootElement.GetProperty("revision").GetString();
    var products = response.RootElement.GetProperty("products");
    if (revision != new CatalogService().Revision() || products.GetArrayLength() != 2 || products[0].GetProperty("name").GetString() != "Mountain Bike")
        throw new Exception("Unexpected catalog API result");
    var page = await client.GetStringAsync("/Index");
    if (!page.Contains("Mountain Bike", StringComparison.Ordinal)) throw new Exception("Razor page differs");
    var asset = Path.Combine(AppContext.BaseDirectory, "wwwroot", "site.css");
    if (File.Exists(asset))
    {
        using var css = await client.GetAsync("/site.css");
        css.EnsureSuccessStatusCode();
        if (css.Headers.ETag is null || await css.Content.ReadAsStringAsync() != await File.ReadAllTextAsync(asset))
            throw new Exception("Published static endpoint differs");
    }
    else if (Environment.GetEnvironmentVariable("EXPECT_PUBLISHED_ASSETS") == "1")
    {
        throw new Exception("Missing published static asset");
    }
    Console.WriteLine("HTTP: " + revision);
    Console.WriteLine("ARCH: " + RuntimeInformation.ProcessArchitecture);
}
finally
{
    await app.StopAsync();
}
