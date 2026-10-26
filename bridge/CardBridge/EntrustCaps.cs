using System;
using System.Collections.Generic;
using System.Drawing.Printing;
using System.Runtime.InteropServices;

namespace CardBridge;

/// <summary>
/// Tamaño de la página del driver en píxeles del dispositivo para cada resolución
/// (GetDeviceCaps sobre el DC de medida). Así el generador manda la imagen a la
/// medida exacta y el puente la dibuja 1:1, sin remuestreo.
/// </summary>
internal static class EntrustCaps
{
    [DllImport("gdi32.dll")] private static extern int GetDeviceCaps(IntPtr hdc, int index);
    private const int HORZRES = 8, VERTRES = 10, LOGPIXELSX = 88, LOGPIXELSY = 90,
        PHYSICALWIDTH = 110, PHYSICALHEIGHT = 111, PHYSICALOFFSETX = 112, PHYSICALOFFSETY = 113;

    public static Dictionary<string, object> Read(string printerName)
    {
        var settings = new PrinterSettings { PrinterName = printerName };
        if (!settings.IsValid) throw new Exception($"impresora no encontrada: {printerName}");

        var papers = new List<string>();
        foreach (PaperSize p in settings.PaperSizes) papers.Add($"{p.PaperName} ({p.Width}x{p.Height})");

        var modes = new List<Dictionary<string, object>>();
        foreach (PrinterResolution r in settings.PrinterResolutions)
        {
            if (r.Kind != PrinterResolutionKind.Custom) continue;
            var ps = (PageSettings)settings.DefaultPageSettings.Clone();
            ps.PrinterResolution = r;
            ps.Landscape = true;
            var paper = CardPaper(settings, r);
            if (paper != null) ps.PaperSize = paper;
            modes.Add(Measure(settings, ps, r, paper?.PaperName));
        }
        return new Dictionary<string, object> { ["papers"] = papers, ["modes"] = modes };
    }

    /// <summary>Papel de tarjeta según la resolución, como el ejemplo del SDK.</summary>
    public static PaperSize CardPaper(PrinterSettings settings, PrinterResolution r)
    {
        PaperSize dtc = null, retransfer = null;
        foreach (PaperSize p in settings.PaperSizes)
        {
            if (p.PaperName == "ISO ID-1 Retransfer") retransfer = p;
            else if (p.PaperName == "ISO ID-1 (85.60 x 53.98 mm)") dtc = p;
        }
        return r.X == 600 && r.Y == 600 ? (retransfer ?? dtc) : dtc;
    }

    /// <summary>Página física y margen físico del DC de impresión, en píxeles del dispositivo.</summary>
    public static (int w, int h, int offX, int offY) PhysicalPage(System.Drawing.Graphics g)
    {
        IntPtr hdc = g.GetHdc();
        try
        {
            return (GetDeviceCaps(hdc, PHYSICALWIDTH), GetDeviceCaps(hdc, PHYSICALHEIGHT),
                    GetDeviceCaps(hdc, PHYSICALOFFSETX), GetDeviceCaps(hdc, PHYSICALOFFSETY));
        }
        finally { g.ReleaseHdc(hdc); }
    }

    public static Dictionary<string, object> Measure(PrinterSettings settings, PageSettings ps, PrinterResolution r, string paper)
    {
        using var g = settings.CreateMeasurementGraphics(ps);
        IntPtr hdc = g.GetHdc();
        try
        {
            return new Dictionary<string, object>
            {
                ["resolution"] = $"{r.X}x{r.Y}",
                ["paper"] = paper,
                ["dpiX"] = GetDeviceCaps(hdc, LOGPIXELSX),
                ["dpiY"] = GetDeviceCaps(hdc, LOGPIXELSY),
                ["printableWidth"] = GetDeviceCaps(hdc, HORZRES),
                ["printableHeight"] = GetDeviceCaps(hdc, VERTRES),
                ["physicalWidth"] = GetDeviceCaps(hdc, PHYSICALWIDTH),
                ["physicalHeight"] = GetDeviceCaps(hdc, PHYSICALHEIGHT),
                ["offsetX"] = GetDeviceCaps(hdc, PHYSICALOFFSETX),
                ["offsetY"] = GetDeviceCaps(hdc, PHYSICALOFFSETY),
            };
        }
        finally { g.ReleaseHdc(hdc); }
    }
}
