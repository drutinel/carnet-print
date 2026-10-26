using System.Runtime.Versioning;
using CarnetPrintService.Api;
using CarnetPrintService.Printing;

[assembly: SupportedOSPlatform("windows")]

var builder = WebApplication.CreateBuilder(new WebApplicationOptions
{
    Args = args,
    ContentRootPath = AppContext.BaseDirectory
});

builder.Host.UseWindowsService(o => o.ServiceName = "CarnetPrintService");

// Solo localhost. El servicio nunca debe quedar expuesto en la red.
string port = builder.Configuration["Service:Port"] ?? "17580";
builder.WebHost.UseUrls($"http://127.0.0.1:{port}");

builder.Services.AddSingleton<DriverRegistry>();
builder.Services.AddSingleton<PrintJobQueue>();
builder.Services.AddHostedService(sp => sp.GetRequiredService<PrintJobQueue>());

// El generador es un archivo local (origen "null"), así que hay que permitirlo.
builder.Services.AddCors(o => o.AddDefaultPolicy(p => p
    .SetIsOriginAllowed(_ => true)
    .AllowAnyHeader()
    .AllowAnyMethod()));

var app = builder.Build();
app.UseCors();

// Límite de cuerpo: dos PNG de tarjeta caben de sobra en 24 MB.
app.Use(async (ctx, next) =>
{
    var f = ctx.Features.Get<Microsoft.AspNetCore.Http.Features.IHttpMaxRequestBodySizeFeature>();
    if (f is { IsReadOnly: false })
        f.MaxRequestBodySize = 24L * 1024 * 1024;
    await next();
});

app.MapGet("/health", () => Results.Ok(new HealthResponse()));

app.MapGet("/printers", (DriverRegistry reg) => Results.Ok(new { printers = reg.List() }));

app.MapPost("/print", (PrintRequest req, PrintJobQueue queue) =>
{
    if (string.IsNullOrWhiteSpace(req.PrinterId))
        return Results.BadRequest(new { error = "Falta printerId." });
    if (string.IsNullOrWhiteSpace(req.Front))
        return Results.BadRequest(new { error = "Falta la imagen del frente." });

    var st = queue.Enqueue(req);
    return st.State == JobState.Error
        ? Results.StatusCode(503)
        : Results.Accepted($"/jobs/{st.JobId}", st);
});

app.MapGet("/jobs/{id}", (string id, PrintJobQueue queue) =>
    queue.Get(id) is { } st ? Results.Ok(st) : Results.NotFound());

app.MapGet("/jobs", (PrintJobQueue queue) => Results.Ok(new { jobs = queue.Recent() }));

app.Logger.LogInformation(
    "CarnetPrintService escuchando en http://127.0.0.1:{port} · tarjeta {w}x{h} px a {dpi} ppp",
    port, Cr80.WidthPx, Cr80.HeightPx, Cr80.Dpi);

app.Run();
