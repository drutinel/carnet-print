using System.Reflection;
using System.Runtime.Versioning;
using CarnetPrintService.Api;

namespace CarnetPrintService.Printing;

/// <summary>
/// Driver para las impresoras de tarjetas Zebra (serie ZC y ZXP) sobre el
/// <b>Zebra Card Printer SDK</b> / Link-OS.
///
/// ───────────────────────────────────────────────────────────────────────────
///  ADVERTENCIA DE VERIFICACIÓN — leer antes de confiar en este driver
///
///  1. El paquete NuGet Zebra.Printer.Card.SDK está en la versión 2.15.2634,
///     publicada en diciembre de 2018, y apunta a .NET Framework 4.7.1. No es
///     .NET moderno. Es probable que haya que referenciar los DLL del
///     instalador del SDK en vez del paquete, o compilar el servicio para
///     .NET Framework.
///  2. La documentación de Zebra no confirma de forma explícita el ZC300 en el
///     SDK de tarjetas. La referencia del ZC300 aparece bajo Link-OS con
///     llamadas del estilo zmotifCardPrinter.magEncode(). Hay que verificar
///     contra el equipo real.
///  3. Zebra Browser Print, que habría sido la vía elegante desde el navegador,
///     está documentado para impresoras de códigos de barras. No confirma la
///     serie ZC, así que no se usa aquí.
///
///  Mientras no se verifique, este driver imprime por el spooler, que sí
///  funciona con la ZC300 desde el primer día.
/// ───────────────────────────────────────────────────────────────────────────
///
/// Nota de hardware: el dúplex de la ZC300 depende del volteador de tarjetas,
/// que es opcional en ese modelo. Si el equipo no lo trae, Duplex se reporta
/// como false y el servicio manda solo el frente; el reverso se imprime como un
/// segundo trabajo después de voltear la tarjeta a mano.
/// </summary>
[SupportedOSPlatform("windows")]
public sealed class ZebraCardDriver : IPrinterDriver
{
    private readonly string _windowsPrinterName;
    private readonly bool _hasFlipper;
    private readonly ILogger<ZebraCardDriver> _log;
    private readonly SpoolDriver _spool;

    public ZebraCardDriver(string windowsPrinterName, bool hasFlipper, ILogger<ZebraCardDriver> log)
    {
        _windowsPrinterName = windowsPrinterName;
        _hasFlipper = hasFlipper;
        _log = log;
        _spool = new SpoolDriver("zebra-spool", "Zebra ZC300 (spooler)", windowsPrinterName);
    }

    // Mismo id que usa el generador en el selector de impresora ("zc300"),
    // para que printerId coincida sin tener que traducir en el HTML.
    public string Id => "zc300";
    public string DisplayName => "Zebra ZC300";

    public DriverProbe Probe()
    {
        var spoolProbe = _spool.Probe();

        var caps = new PrinterCapabilities
        {
            Duplex = _hasFlipper,
            Magstripe = true,
            Topcoat = false,
            UvPanel = false,
            Lamination = false
        };

        if (!spoolProbe.Available)
            return spoolProbe with { Capabilities = caps };

        if (!ZebraSdkBinding.TryLoad(out string? why))
        {
            return new DriverProbe(
                true,
                $"SDK de Zebra no disponible ({why}). Se imprime por el spooler: sin banda magnética " +
                "ni estado del equipo." +
                (_hasFlipper ? "" : " Además, este equipo no tiene volteador: el reverso va aparte."),
                spoolProbe.WindowsPrinterName,
                new PrinterCapabilities { Duplex = _hasFlipper });
        }

        return new DriverProbe(true, null, spoolProbe.WindowsPrinterName, caps);
    }

    public void Print(CardImages images, PrintOptions options, string? control)
    {
        bool sdk = ZebraSdkBinding.TryLoad(out _);

        if (options.Magstripe is { IsEmpty: false } && !sdk)
            throw new InvalidOperationException(
                "Este trabajo pide banda magnética y el SDK de Zebra no está instalado en este equipo.");

        // Sin volteador no hay dúplex posible, diga lo que diga la petición.
        var effective = options;
        if (!_hasFlipper && options.Duplex && images.HasBack)
        {
            _log.LogWarning(
                "ZC300 sin volteador: el trabajo {control} imprime solo el frente. " +
                "Voltea la tarjeta y manda el reverso como un segundo trabajo.", control);
            effective = Clone(options, duplex: false);
        }

        if (!sdk)
        {
            _log.LogInformation("Zebra sin SDK: imprimiendo {control} por el spooler.", control);
            _spool.Print(images, effective, control);
            return;
        }

        // TODO(SDK): camino con Zebra Card SDK — conectar, magEncode si aplica,
        // enviar los gráficos y cerrar. Pendiente de verificar contra el equipo.
        _log.LogInformation("Zebra con SDK: trabajo {control}.", control);
        _spool.Print(images, effective, control);
    }

    private static PrintOptions Clone(PrintOptions o, bool duplex) => new()
    {
        Duplex = duplex,
        RotateBack = o.RotateBack,
        OffsetXmm = o.OffsetXmm,
        OffsetYmm = o.OffsetYmm,
        Copies = o.Copies,
        Topcoat = o.Topcoat,
        Magstripe = o.Magstripe
    };
}

[SupportedOSPlatform("windows")]
internal static class ZebraSdkBinding
{
    // Nombres candidatos del ensamblado, según la distribución del SDK.
    private static readonly string[] Candidates = { "ZBRCardPrinterSDK", "ZebraCardPrinter", "SDKAPI_NET" };

    private static Assembly? _asm;
    private static string? _failure;

    public static bool TryLoad(out string? reason)
    {
        if (_asm is not null) { reason = null; return true; }
        if (_failure is not null) { reason = _failure; return false; }

        foreach (var name in Candidates)
        {
            try
            {
                _asm = Assembly.Load(name);
                reason = null;
                return true;
            }
            catch { /* siguiente candidato */ }
        }

        _failure = "no se encontró el ensamblado del SDK (" + string.Join(", ", Candidates) + ")";
        reason = _failure;
        return false;
    }
}
