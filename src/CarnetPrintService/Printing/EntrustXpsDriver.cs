using System.Reflection;
using System.Runtime.Versioning;
using CarnetPrintService.Api;

namespace CarnetPrintService.Printing;

/// <summary>
/// Driver para las impresoras Entrust (Sigma DS1/DS2/DS3, SD, CD, CE840, CL900)
/// sobre el <b>XPS Card Printer Driver SDK</b>.
///
/// ───────────────────────────────────────────────────────────────────────────
///  ADVERTENCIA DE VERIFICACIÓN
///  Este archivo se escribió contra la guía de referencia publicada del SDK
///  (527250-003f). No se pudo ejecutar contra el SDK ni contra la impresora
///  durante su desarrollo. Antes de usarlo en producción hay que:
///    1. Instalar «XPS Card Printer Driver SDK v8.8» desde el soporte de Entrust.
///    2. Confirmar el nombre y la firma de los tipos del ensamblado en
///       EntrustSdkBinding (abajo), con el Examinador de objetos de Visual Studio.
///    3. Probar primero sin cinta, con la tapa abierta, para ver el movimiento
///       de la tarjeta sin gastar material.
///  Mientras eso no esté hecho, el servicio seguirá usando SpoolDriver, que sí
///  imprime y no depende del SDK.
/// ───────────────────────────────────────────────────────────────────────────
///
/// Cómo funciona el SDK, según la referencia:
///   • <b>Print Ticket</b>: sobrescribe las preferencias del driver por trabajo
///     (una o dos caras, orientación por cara, giro 180°, desactivar una cara,
///     laminación, debow, impress).
///   • <b>Modo interactivo</b>: StartJob por IBidiSpl → operaciones de tarjeta →
///     imprimir por la interfaz de Windows → EndJob. Es el modo que hace falta
///     para banda magnética, tarjeta inteligente y monitoreo de estado.
///   • <b>Escapes de texto</b>: topcoat, bloqueo de impresión, banda magnética y
///     grabado. Las cadenas exactas están en escapes.json, no empotradas aquí,
///     porque dependen de la versión del driver.
///
/// El panel UV o luster no se "activa": se pinta con el color RGB(217,217,217)
/// sobre una cinta que tenga ese panel. Eso se resuelve en el diseño del carnet,
/// no en este código.
/// </summary>
[SupportedOSPlatform("windows")]
public sealed class EntrustXpsDriver : IPrinterDriver
{
    private readonly string _windowsPrinterName;
    private readonly EscapeTable _escapes;
    private readonly ILogger<EntrustXpsDriver> _log;
    private readonly SpoolDriver _spool;

    public EntrustXpsDriver(string windowsPrinterName, EscapeTable escapes, ILogger<EntrustXpsDriver> log)
    {
        _windowsPrinterName = windowsPrinterName;
        _escapes = escapes;
        _log = log;
        _spool = new SpoolDriver("entrust-spool", "ENTRUST (spooler)", windowsPrinterName);
    }

    public string Id => "entrust";
    public string DisplayName => "ENTRUST · Sigma DS3";

    public DriverProbe Probe()
    {
        var spoolProbe = _spool.Probe();

        var caps = new PrinterCapabilities
        {
            Duplex = true,
            Magstripe = true,
            Topcoat = true,
            UvPanel = true,
            Lamination = true
        };

        if (!spoolProbe.Available)
            return spoolProbe with { Capabilities = caps };

        if (!EntrustSdkBinding.TryLoad(out string? why))
        {
            // La impresora está, el SDK no. Se puede imprimir igual, sin extras.
            return new DriverProbe(
                true,
                $"SDK de Entrust no disponible ({why}). Se imprime por el spooler: " +
                "sin banda magnética, topcoat ni estado del equipo.",
                spoolProbe.WindowsPrinterName,
                new PrinterCapabilities { Duplex = true });
        }

        return new DriverProbe(true, null, spoolProbe.WindowsPrinterName, caps);
    }

    public void Print(CardImages images, PrintOptions options, string? control)
    {
        bool sdk = EntrustSdkBinding.TryLoad(out _);
        bool needsSdk = (options.Magstripe is { IsEmpty: false })
                        || !string.Equals(options.Topcoat, "full", StringComparison.OrdinalIgnoreCase);

        if (!sdk)
        {
            if (needsSdk)
                throw new InvalidOperationException(
                    "Este trabajo pide banda magnética o topcoat personalizado, y el SDK de Entrust " +
                    "no está instalado en este equipo. Instálalo, o manda el trabajo sin esas opciones.");

            _log.LogInformation("Entrust sin SDK: imprimiendo {control} por el spooler.", control);
            _spool.Print(images, options, control);
            return;
        }

        // Camino con SDK. Secuencia según la referencia del fabricante.
        _log.LogInformation("Entrust con SDK: trabajo {control} en modo {mode}.",
            control, needsSdk ? "interactivo" : "print ticket");

        using var job = EntrustSdkBinding.StartJob(_windowsPrinterName);
        try
        {
            job.ApplyPrintTicket(
                duplex: options.Duplex && images.HasBack,
                rotateBack: options.RotateBack);

            if (!string.Equals(options.Topcoat, "full", StringComparison.OrdinalIgnoreCase))
                job.SendEscape(_escapes.Topcoat(options.Topcoat));

            if (options.Magstripe is { IsEmpty: false } mag)
            {
                if (!string.IsNullOrWhiteSpace(mag.Track1)) job.SendEscape(_escapes.MagTrack(1, mag.Track1!));
                if (!string.IsNullOrWhiteSpace(mag.Track2)) job.SendEscape(_escapes.MagTrack(2, mag.Track2!));
                if (!string.IsNullOrWhiteSpace(mag.Track3)) job.SendEscape(_escapes.MagTrack(3, mag.Track3!));
            }

            // El envío de los gráficos usa la interfaz de impresión de Windows,
            // igual que el spooler, pero dentro del StartJob/EndJob del SDK.
            _spool.Print(images, options, control);

            job.Commit();
        }
        catch
        {
            job.Cancel();
            throw;
        }
    }
}

/// <summary>
/// Carga el SDK de Entrust por reflexión, de modo que el servicio compila y
/// arranca en equipos donde el SDK no está instalado.
///
/// Los nombres de tipo son los que hay que confirmar contra el ensamblado real
/// (ver ADVERTENCIA en EntrustXpsDriver).
/// </summary>
[SupportedOSPlatform("windows")]
internal static class EntrustSdkBinding
{
    private const string AssemblyName = "dxp01sdk";
    private static Assembly? _asm;
    private static string? _failure;

    public static bool TryLoad(out string? reason)
    {
        if (_asm is not null) { reason = null; return true; }
        if (_failure is not null) { reason = _failure; return false; }

        try
        {
            _asm = Assembly.Load(AssemblyName);
            reason = null;
            return true;
        }
        catch (Exception ex)
        {
            _failure = $"no se pudo cargar {AssemblyName}: {ex.GetType().Name}";
            reason = _failure;
            return false;
        }
    }

    public static EntrustJob StartJob(string printerName) => new(printerName);
}

/// <summary>
/// Envoltura del ciclo StartJob → operaciones → EndJob del SDK de Entrust.
/// Los cuerpos marcados con TODO son los que hay que completar contra el
/// ensamblado real; la estructura y el orden de llamadas sí siguen la referencia.
/// </summary>
[SupportedOSPlatform("windows")]
internal sealed class EntrustJob : IDisposable
{
    private readonly string _printer;
    private bool _committed;

    public EntrustJob(string printerName)
    {
        _printer = printerName;
        // TODO(SDK): StartJob por IBidiSpl.
    }

    public void ApplyPrintTicket(bool duplex, bool rotateBack)
    {
        // TODO(SDK): Print Ticket — una o dos caras, giro del reverso.
        // La referencia aclara que esta ruta no existe desde Java; en C# sí.
    }

    public void SendEscape(string escape)
    {
        if (string.IsNullOrWhiteSpace(escape)) return;
        // TODO(SDK): enviar el escape de texto por el flujo de impresión.
    }

    public void Commit()
    {
        // TODO(SDK): EndJob, después de que los datos llegaron al spooler.
        _committed = true;
    }

    public void Cancel()
    {
        // TODO(SDK): Action request de cancelación.
        _committed = true;
    }

    public void Dispose()
    {
        if (!_committed) Cancel();
    }
}
