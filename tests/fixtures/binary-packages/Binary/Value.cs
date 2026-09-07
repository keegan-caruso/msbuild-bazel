namespace RulesMsbuild.Binary;

public static class Value
{
    public static string Read() => "binary-v1/" + Leaf.Value.Read();
}
