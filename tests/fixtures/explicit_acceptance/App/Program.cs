using System;
using System.IO;
using System.Reflection;

using var s = Assembly.GetExecutingAssembly().GetManifestResourceStream("message");
using var r = new StreamReader(s!);
Console.WriteLine(Value.Get() + ":" + r.ReadToEnd() + ":" + File.ReadAllText("data.txt"));
return args.Length > 0 || File.ReadAllText("library-data.txt") != "dependency-data" ? 1 : 0;
