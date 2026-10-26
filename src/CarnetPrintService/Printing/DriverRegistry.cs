using System.Runtime.Versioning;
using CarnetPrintService.Api;

namespace CarnetPrintService.Printing;

[SupportedOSPlatform("windows")]
public sealed class DriverRegistry
{
    private readonly List<IPrinterDriver> _drivers = new();

    public DriverRegistry(IConfiguration cfg, ILoggerFactory lf)
    {
        var log = lf.CreateLogger<DriverRegistry>();
        var escapes = EscapeTable.Load(
            Path.Combine(AppContext.BaseDirectory, "escapes.json"),
            lf.CreateLogger<EscapeTable>());

        string entrustName = cfg["Printers:Entrust:WindowsName"] ?? "ENTRUST";
        string zebraName   = cfg["Printers:Zebra:WindowsName"]   ?? "ZC300";
        bool zebraFlipper  = cfg.GetValue("Printers:Zebra:HasFlipper", false);

        _drivers.Add(new EntrustXpsDriver(entrustName, escapes, lf.CreateLogger<EntrustXpsDriver>()));
        _drivers.Add(new ZebraCardDriver(zebraName, zebraFlipper, lf.CreateLogger<ZebraCardDriver>()));

        log.LogInformation("Drivers registrados: {list}", string.Join(", ", _drivers.Select(d => d.Id)));
    }

    public IPrinterDriver? Find(string id) =>
        _drivers.FirstOrDefault(d => string.Equals(d.Id, id, StringComparison.OrdinalIgnoreCase));

    public IReadOnlyList<PrinterInfo> List() => _drivers.Select(d =>
    {
        var p = d.Probe();
        return new PrinterInfo
        {
            Id = d.Id,
            Name = d.DisplayName,
            Driver = d.GetType().Name,
            WindowsName = p.WindowsPrinterName,
            Available = p.Available,
            Reason = p.Reason,
            Capabilities = p.Capabilities
        };
    }).ToList();
}
