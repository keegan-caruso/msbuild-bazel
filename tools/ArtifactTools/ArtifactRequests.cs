internal sealed record Input(string Source, string Path);
internal sealed record TestProtocolRequest(string Entry, string Assembly, Input[] Data, TestOptions TestOptions, RuntimeHost? RuntimeHost = null);
