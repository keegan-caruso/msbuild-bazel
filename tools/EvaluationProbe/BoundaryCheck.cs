using System.Net.Sockets;
using System.Text.Json;

internal static class BoundaryCheck
{
    public static void Run(string path, JsonSerializerOptions options)
    {
        var request = JsonSerializer.Deserialize<Request>(File.ReadAllText(path), options) ?? throw new InvalidDataException("empty request");
        var readDenied = false;
        var writeDenied = false;
        var networkDenied = false;
        try { _ = File.ReadAllText(request.ExternalFile); }
        catch (UnauthorizedAccessException) { readDenied = true; }
        try { File.AppendAllText(request.SealedFile, "unexpected write"); }
        catch (UnauthorizedAccessException) { writeDenied = true; }
        try
        {
            using var client = new TcpClient();
            client.Connect("127.0.0.1", request.Port);
        }
        catch (SocketException error) when (error.SocketErrorCode == SocketError.AccessDenied)
        {
            networkDenied = true;
        }
        File.WriteAllText(request.Output, JsonSerializer.Serialize(new { readDenied, writeDenied, networkDenied }, options));
    }

    private sealed record Request(string ExternalFile, string SealedFile, int Port, string Output);
}
