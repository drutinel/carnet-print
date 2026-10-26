using CarnetPrintService.Api;

namespace CarnetPrintService.Printing;

/// <summary>
/// Un driver sabe hablar con una familia de impresoras. El servicio no conoce
/// detalles de Entrust ni de Zebra: solo esta interfaz.
/// </summary>
public interface IPrinterDriver
{
    /// <summary>Identificador corto y estable: "entrust", "zebra", "spool".</summary>
    string Id { get; }

    /// <summary>Nombre para mostrar al operador.</summary>
    string DisplayName { get; }

    /// <summary>
    /// Comprueba si el driver puede usarse en esta PC: SDK instalado, cola de
    /// impresión presente, etc. Se llama al arrancar y cada vez que se listan
    /// las impresoras, de modo que enchufar la impresora no obliga a reiniciar.
    /// </summary>
    DriverProbe Probe();

    /// <summary>Imprime una tarjeta. Bloquea hasta que el trabajo entra en la cola del sistema.</summary>
    void Print(CardImages images, PrintOptions options, string? control);
}

/// <summary>Resultado de comprobar un driver.</summary>
public sealed record DriverProbe(
    bool Available,
    string? Reason,
    string WindowsPrinterName,
    PrinterCapabilities Capabilities);

/// <summary>Las dos caras ya rasterizadas a 300 ppp, listas para el papel.</summary>
public sealed class CardImages : IDisposable
{
    public required System.Drawing.Bitmap Front { get; init; }
    public System.Drawing.Bitmap? Back { get; init; }

    public bool HasBack => Back is not null;

    public void Dispose()
    {
        Front.Dispose();
        Back?.Dispose();
    }
}
