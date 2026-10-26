using System.Collections.Concurrent;
using System.Runtime.Versioning;
using CarnetPrintService.Api;

namespace CarnetPrintService.Printing;

/// <summary>
/// Cola de un solo hilo. Las impresoras de tarjetas tienen una sola ranura: dos
/// trabajos a la vez no van más rápido, solo se estorban. Serializar aquí evita
/// además que dos pestañas del generador manden a la vez.
/// </summary>
[SupportedOSPlatform("windows")]
public sealed class PrintJobQueue : BackgroundService
{
    private readonly record struct Item(string JobId, PrintRequest Request);

    private readonly BlockingCollection<Item> _queue = new(new ConcurrentQueue<Item>(), 64);
    private readonly ConcurrentDictionary<string, JobStatus> _status = new();
    private readonly DriverRegistry _drivers;
    private readonly ILogger<PrintJobQueue> _log;

    public PrintJobQueue(DriverRegistry drivers, ILogger<PrintJobQueue> log)
    {
        _drivers = drivers;
        _log = log;
    }

    public JobStatus Enqueue(PrintRequest req)
    {
        var st = new JobStatus
        {
            JobId = "J-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Random.Shared.Next(1000, 9999),
            PrinterId = req.PrinterId,
            Control = req.Control,
            State = JobState.Queued
        };
        _status[st.JobId] = st;

        if (!_queue.TryAdd(new Item(st.JobId, req)))
        {
            st.State = JobState.Error;
            st.Message = "La cola de impresión está llena. Espera a que terminen los trabajos pendientes.";
            st.FinishedAt = DateTimeOffset.Now;
        }
        return st;
    }

    public JobStatus? Get(string jobId) => _status.TryGetValue(jobId, out var s) ? s : null;

    public IReadOnlyCollection<JobStatus> Recent(int take = 25) =>
        _status.Values.OrderByDescending(s => s.CreatedAt).Take(take).ToList();

    protected override Task ExecuteAsync(CancellationToken stoppingToken) =>
        Task.Factory.StartNew(() => Loop(stoppingToken), TaskCreationOptions.LongRunning);

    private void Loop(CancellationToken ct)
    {
        foreach (var item in _queue.GetConsumingEnumerable(ct))
        {
            var st = _status[item.JobId];
            try
            {
                st.State = JobState.Printing;

                var driver = _drivers.Find(item.Request.PrinterId)
                    ?? throw new InvalidOperationException(
                        $"No conozco una impresora con el id «{item.Request.PrinterId}».");

                var probe = driver.Probe();
                if (!probe.Available)
                    throw new InvalidOperationException(probe.Reason ?? "La impresora no está disponible.");

                using var images = Rendering.CardRenderer.FromRequest(item.Request);
                driver.Print(images, item.Request.Options, item.Request.Control);

                st.State = JobState.Done;
                st.Message = probe.Reason; // avisos no fatales, p. ej. "sin SDK"
                _log.LogInformation("Trabajo {job} ({control}) impreso en {printer}.",
                    st.JobId, st.Control, driver.DisplayName);
            }
            catch (Exception ex)
            {
                st.State = JobState.Error;
                st.Message = ex.Message;
                _log.LogError(ex, "Falló el trabajo {job} ({control}).", st.JobId, st.Control);
            }
            finally
            {
                st.FinishedAt = DateTimeOffset.Now;
            }
        }
    }
}
