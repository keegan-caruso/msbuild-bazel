using Catalog;

var catalog = new CatalogService();
var products = catalog.All();
if (products.Count != 2 || products[0].Name != "Mountain Bike" || products[1].Price != 49m)
    throw new Exception("Catalog data/package behavior differs");
Console.WriteLine("UNIT: " + catalog.Revision());
