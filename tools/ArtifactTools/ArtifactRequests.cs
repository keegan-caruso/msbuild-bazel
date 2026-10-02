internal sealed record Input(string Source, string Path);
internal sealed record Launch(string Entry, string Assembly, bool Test, Input[] Data, TestOptions? TestOptions = null, RuntimeHost? RuntimeHost = null);
