using System;
using Microsoft.Extensions.Options;
using NuGetQualification;

var options = Options.Create(Library.Value());
if (options.Value != "\"locked\"") throw new Exception("Resolved package behavior differs");
Console.WriteLine("PASS: central versions, transitive Options and locked Newtonsoft");
