using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

var builder = Host.CreateApplicationBuilder(new HostApplicationBuilderSettings { ContentRootPath = AppContext.BaseDirectory });
builder.Services.AddHostedService<Worker>();
using var host = builder.Build();
await host.RunAsync();

class Worker(IConfiguration configuration, IHostApplicationLifetime lifetime) : BackgroundService
{
    protected override Task ExecuteAsync(CancellationToken stoppingToken)
    {
        Console.WriteLine($"WORKER:{Library.Value()}:{configuration["Proof"]}");
        lifetime.StopApplication();
        return Task.CompletedTask;
    }
}
