using Newtonsoft.Json;

namespace NuGetQualification;

public sealed class Library
{
    public static string Value() => JsonConvert.SerializeObject("locked");
}
