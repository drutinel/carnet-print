using System.Drawing;
using System.Drawing.Printing;
using System.Runtime.Versioning;
using CarnetPrintService.Api;

namespace CarnetPrintService.Printing;

/// <summary>
/// Imprime por el spooler de Windows, usando el driver que ya tiene instalado la
/// impresora. No necesita ningún SDK.
///
/// Esto es lo que resuelve el problema de calibración del generador anterior: el
/// tamaño de página se fija aquí en centésimas de pulgada exactas (337 x 213),
/// los márgenes van en cero y la imagen se dibuja en coordenadas absolutas. El
/// navegador ya no interviene, así que no hay escalado que adivinar.
///
/// Funciona con la ENTRUST y con la ZC300 el mismo día que se instala, aunque sin
/// banda magnética, topcoat ni control de estado: para eso están los otros drivers.
/// </summary>
[SupportedOSPlatform("windows")]
public sealed class SpoolDriver : IPrinterDriver
{
    private readonly string _windowsPrinterName;
    private readonly string _id;
    private readonly string _display;

    public SpoolDriver(string id, string displayName, string windowsPrinterName)
    {
        _id = id;
        _display = displayName;
        _windowsPrinterName = windowsPrinterName;
    }

    public string Id => _id;
    public string DisplayName => _display;

    public DriverProbe Probe()
    {
        var caps = new PrinterCapabilities
        {
            Duplex = true,      // lo decide el driver de Windows; aquí solo mandamos dos páginas
            Magstripe = false,
            Topcoat = false,
            UvPanel = false,
            Lamination = false
        };

        foreach (string name in PrinterSettings.InstalledPrinters)
        {
            if (string.Equals(name, _windowsPrinterName, StringComparison.OrdinalIgnoreCase))
            {
                var settings = new PrinterSettings { PrinterName = name };
                return settings.IsValid
                    ? new DriverProbe(true, null, name, caps)
                    : new DriverProbe(false, $"Windows reporta la impresora «{name}» como no válida.", name, caps);
            }
        }

        return new DriverProbe(
            false,
            $"No encuentro una impresora llamada «{_windowsPrinterName}» en este equipo. " +
            "Revisa el nombre exacto en Configuración → Impresoras y escáneres, y ajústalo en appsettings.json.",
            _windowsPrinterName,
            caps);
    }

    public void Print(CardImages images, PrintOptions options, string? control)
    {
        var probe = Probe();
        if (!probe.Available)
            throw new InvalidOperationException(probe.Reason);

        // Cada cara es una página CR80. El driver de la impresora las usa para el dúplex.
        var pages = new List<Bitmap> { images.Front };
        if (images.HasBack && options.Duplex) pages.Add(images.Back!);

        int pageIndex = 0;

        using var doc = new PrintDocument();
        doc.DocumentName = string.IsNullOrWhiteSpace(control) ? "Carnet" : $"Carnet {control}";
        doc.PrinterSettings.PrinterName = probe.WindowsPrinterName;
        doc.PrinterSettings.Copies = (short)Math.Clamp(options.Copies, 1, 50);
        doc.OriginAtMargins = false;

        doc.DefaultPageSettings.PaperSize =
            new PaperSize("CR80", Cr80.WidthHundredthsInch, Cr80.HeightHundredthsInch);
        doc.DefaultPageSettings.Margins = new Margins(0, 0, 0, 0);
        doc.DefaultPageSettings.Landscape = false;

        doc.PrintPage += (_, e) =>
        {
            if (e.Graphics is null) return;

            var bmp = pages[pageIndex];
            bool rotate = options.RotateBack && pageIndex == 1;

            // Lienzo en centésimas de pulgada, igual que el tamaño de papel.
            e.Graphics.PageUnit = GraphicsUnit.Display; // 1/100 pulgada
            e.Graphics.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic;
            e.Graphics.PixelOffsetMode = System.Drawing.Drawing2D.PixelOffsetMode.HighQuality;

            float w = Cr80.WidthHundredthsInch;
            float h = Cr80.HeightHundredthsInch;
            float ox = (float)(options.OffsetXmm / 25.4 * 100);
            float oy = (float)(options.OffsetYmm / 25.4 * 100);

            var state = e.Graphics.Save();
            e.Graphics.TranslateTransform(ox, oy);
            if (rotate)
            {
                e.Graphics.TranslateTransform(w / 2f, h / 2f);
                e.Graphics.RotateTransform(180f);
                e.Graphics.TranslateTransform(-w / 2f, -h / 2f);
            }
            e.Graphics.DrawImage(bmp, new RectangleF(0, 0, w, h));
            e.Graphics.Restore(state);

            pageIndex++;
            e.HasMorePages = pageIndex < pages.Count;
        };

        doc.Print();
    }
}
