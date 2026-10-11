using Catalog;
using Microsoft.Extensions.Options;

var catalog = new CatalogService();
var products = Options.Create(catalog.All()).Value;
if (products.Count != 2 || products[0].Name != "Mountain Bike" || products[1].Price != 49m)
    throw new Exception("Catalog data/package behavior differs");
Console.WriteLine("UNIT: " + catalog.Revision());
