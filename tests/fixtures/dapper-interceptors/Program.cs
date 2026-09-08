using Dapper;
using System.Data;
using System.Data.Common;
using System.Diagnostics;
using System.Runtime.CompilerServices;
[module: DapperAot]
using var connection = new FakeConnection();
var result = connection.ExecuteScalar<int>("select 42");
Console.WriteLine($"intercepted:{result}");
if (result != 42) throw new Exception("Wrong query result");
sealed class FakeConnection : DbConnection
{
    [System.Diagnostics.CodeAnalysis.AllowNull]
    public override string ConnectionString { get; set; } = "";
    public override string Database => "probe";
    public override string DataSource => "probe";
    public override string ServerVersion => "1";
    public override ConnectionState State => ConnectionState.Open;
    public override void ChangeDatabase(string value) { }
    public override void Open() { }
    public override void Close() { }
    protected override DbTransaction BeginDbTransaction(IsolationLevel value) => throw new NotSupportedException();
    protected override DbCommand CreateDbCommand() => new FakeCommand(this);
}
sealed class FakeCommand(DbConnection connection) : DbCommand
{
    [System.Diagnostics.CodeAnalysis.AllowNull]
    public override string CommandText { get; set; } = "";
    public override int CommandTimeout { get; set; }
    public override CommandType CommandType { get; set; }
    public override bool DesignTimeVisible { get; set; }
    public override UpdateRowSource UpdatedRowSource { get; set; }
    protected override DbConnection? DbConnection { get; set; } = connection;
    protected override DbTransaction? DbTransaction { get; set; }
    protected override DbParameterCollection DbParameterCollection { get; } = new EmptyParameters();
    public override void Cancel() { }
    public override void Prepare() { }
    protected override DbParameter CreateDbParameter() => throw new NotSupportedException();
    protected override DbDataReader ExecuteDbDataReader(CommandBehavior value) => throw new NotSupportedException();
    public override int ExecuteNonQuery() => throw new NotSupportedException();
    [MethodImpl(MethodImplOptions.NoInlining)]
    public override object ExecuteScalar()
    {
        var stack = new StackTrace().ToString();
        if (!stack.Contains("Dapper.Command") || stack.Contains("Dapper.SqlMapper")) throw new Exception("Dapper AOT interception did not execute: " + stack);
        return int.Parse(CommandText.Split(' ')[1]);
    }
}

sealed class EmptyParameters : DbParameterCollection
{
    private readonly List<DbParameter> values = [];
    public override int Count => values.Count;
    public override object SyncRoot => ((System.Collections.ICollection)values).SyncRoot;
    public override int Add(object value) { values.Add((DbParameter)value); return values.Count - 1; }
    public override void AddRange(Array items) { foreach (var item in items) Add(item!); }
    public override void Clear() => values.Clear();
    public override bool Contains(object value) => values.Contains((DbParameter)value);
    public override bool Contains(string value) => IndexOf(value) >= 0;
    public override void CopyTo(Array array, int index) => ((System.Collections.ICollection)values).CopyTo(array, index);
    public override System.Collections.IEnumerator GetEnumerator() => values.GetEnumerator();
    public override int IndexOf(object value) => values.IndexOf((DbParameter)value);
    public override int IndexOf(string value) => values.FindIndex(p => p.ParameterName == value);
    public override void Insert(int index, object value) => values.Insert(index, (DbParameter)value);
    public override void Remove(object value) => values.Remove((DbParameter)value);
    public override void RemoveAt(int index) => values.RemoveAt(index);
    public override void RemoveAt(string value) => RemoveAt(IndexOf(value));
    protected override DbParameter GetParameter(int index) => values[index];
    protected override DbParameter GetParameter(string value) => values[IndexOf(value)];
    protected override void SetParameter(int index, DbParameter value) => values[index] = value;
    protected override void SetParameter(string name, DbParameter value) => SetParameter(IndexOf(name), value);
}
