using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Printing;
using System.IO;
using System.Printing;
using System.Printing.Interop;
using System.Runtime.InteropServices;
using System.Xml;
using dxp01sdk;

namespace CardBridge;

/// <summary>
/// PrintDocument de una o dos caras para el driver XPS de Entrust.
///
/// Calidad:
///  • La imagen se dibuja 1:1 en píxeles del dispositivo cuando mide lo mismo que
///    la página del driver (DS3 a 300 ppp: 1015×640, ver `CardBridge caps`); si no,
///    se escala a la página con bicúbica.
///  • Capa negra aparte (--front-k/--back-k): sus píxeles negros se pegan en negro
///    puro (0,0,0) sobre la imagen de color y el Print Ticket activa
///    DocumentPrintBlackImagePixelsUsingMonochrome, así el driver los imprime con el
///    panel K (resina) en vez de negro compuesto.
///  • El Print Ticket va solo en este trabajo (DEVMODE), sin tocar las preferencias
///    del driver en la PC; si la conversión falla se usa Commit() como en el ejemplo.
/// </summary>
internal sealed class EntrustCardDocument : PrintDocument
{
    private readonly EntrustPrintJob _job;
    private readonly Bitmap _front;
    private readonly Bitmap _back;
    private readonly bool _twoPages;
    private readonly bool _hasK;
    private int _page;

    public string TicketMode { get; private set; } = "";

    public EntrustCardDocument(EntrustPrintJob job, PrinterOptionsValues options)
    {
        _job = job;
        _front = Compose(job.FrontPath, job.FrontKPath);
        _back = Compose(job.BackPath, job.BackKPath);
        _hasK = !string.IsNullOrEmpty(job.FrontKPath) || !string.IsNullOrEmpty(job.BackKPath);
        _twoPages = _back != null;

        // Solo reverso: se manda un frente vacío y se desactiva su impresión.
        if (_front == null && _job.DisablePrinting == "off")
            _job.DisablePrinting = "front";

        PrinterSettings.PrinterName = job.PrinterName;
        DocumentName = job.DocumentName;
        PrintController = new StandardPrintController();
        ApplyTicket();
        SelectPaperAndResolution(options);
    }

    // ---------- Imágenes ----------

    private static Bitmap Load(string path)
    {
        // Copia en memoria (24 bpp) para no dejar el archivo bloqueado.
        using var fs = File.OpenRead(path);
        using var tmp = Image.FromStream(fs);
        var bmp = new Bitmap(tmp.Width, tmp.Height, PixelFormat.Format24bppRgb);
        bmp.SetResolution(300, 300);
        using var g = Graphics.FromImage(bmp);
        g.Clear(Color.White);
        g.DrawImageUnscaled(tmp, 0, 0);
        return bmp;
    }

    /// <summary>Negro puro (0,0,0) -> (0,0,5): se imprime con YMC y no tapa el color con el panel K.</summary>
    private static void NearBlack(Bitmap bmp)
    {
        var rect = new Rectangle(0, 0, bmp.Width, bmp.Height);
        var d = bmp.LockBits(rect, ImageLockMode.ReadWrite, PixelFormat.Format24bppRgb);
        try
        {
            var buf = new byte[d.Stride * d.Height];
            Marshal.Copy(d.Scan0, buf, 0, buf.Length);
            for (int y = 0; y < d.Height; y++)
            {
                int i = y * d.Stride;
                for (int x = 0; x < d.Width; x++, i += 3)
                    if (buf[i] == 0 && buf[i + 1] == 0 && buf[i + 2] == 0) buf[i] = 5;   // BGR: azul = 5
            }
            Marshal.Copy(buf, 0, d.Scan0, buf.Length);
        }
        finally { bmp.UnlockBits(d); }
    }

    /// <summary>Color + capa K: cada píxel oscuro de la capa K pasa a negro puro.</summary>
    private static Bitmap Compose(string colorPath, string kPath)
    {
        if (string.IsNullOrEmpty(colorPath) && string.IsNullOrEmpty(kPath)) return null;
        Bitmap color = !string.IsNullOrEmpty(colorPath) ? Load(colorPath) : null;
        // El negro puro (0,0,0) lo imprime el driver con el panel K, encima del color
        // (guía Entrust: usar 0,0,5 para negros que deben salir con YMC). Solo la capa K debe ser K.
        if (color != null) NearBlack(color);
        if (string.IsNullOrEmpty(kPath)) return color;

        using var k = Load(kPath);
        if (color == null)
        {
            color = new Bitmap(k.Width, k.Height, PixelFormat.Format24bppRgb);
            color.SetResolution(300, 300);
            using var g = Graphics.FromImage(color);
            g.Clear(Color.White);
        }
        if (k.Width != color.Width || k.Height != color.Height)
            throw new Exception($"la capa K ({k.Width}x{k.Height}) no mide lo mismo que la cara ({color.Width}x{color.Height})");

        var rect = new Rectangle(0, 0, color.Width, color.Height);
        var cd = color.LockBits(rect, ImageLockMode.ReadWrite, PixelFormat.Format24bppRgb);
        var kd = k.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb);
        try
        {
            int bytes = cd.Stride * cd.Height;
            var cb = new byte[bytes];
            var kb = new byte[kd.Stride * kd.Height];
            Marshal.Copy(cd.Scan0, cb, 0, bytes);
            Marshal.Copy(kd.Scan0, kb, 0, kb.Length);
            for (int y = 0; y < cd.Height; y++)
            {
                int ci = y * cd.Stride, ki = y * kd.Stride;
                for (int x = 0; x < cd.Width; x++, ci += 3, ki += 3)
                {
                    // BGR; luminancia aproximada < 128 = tinta negra.
                    int lum = (kb[ki] * 29 + kb[ki + 1] * 150 + kb[ki + 2] * 77) >> 8;
                    if (lum < 128) cb[ci] = cb[ci + 1] = cb[ci + 2] = 0;
                }
            }
            Marshal.Copy(cb, 0, cd.Scan0, bytes);
        }
        finally
        {
            color.UnlockBits(cd);
            k.UnlockBits(kd);
        }
        return color;
    }

    // ---------- Página, resolución y Print Ticket ----------

    private void SelectPaperAndResolution(PrinterOptionsValues options)
    {
        // Como el ejemplo del SDK: 300 ppp → "ISO ID-1 (85.60 x 53.98 mm)";
        // 600 ppp (retransferencia) → "ISO ID-1 Retransfer".
        string res = options._colorPrintResolution ?? "";
        foreach (PrinterResolution r in PrinterSettings.PrinterResolutions)
        {
            bool ok = (r.X == 600 && r.Y == 600 && res.Contains("600x600"))
                      || (r.X == 300 && r.Y == 300 && res.Contains("300x300"));
            if (!ok) continue;
            DefaultPageSettings.PrinterResolution = r;
            var paper = EntrustCaps.CardPaper(PrinterSettings, r);
            if (paper != null) DefaultPageSettings.PaperSize = paper;
            return;
        }
    }

    private static bool IsLandscape(Image img) => img == null || img.Width >= img.Height;

    private void ApplyTicket()
    {
        var queue = new PrintQueue(new LocalPrintServer(), PrinterSettings.PrinterName);
        var delta = new PrintTicket
        {
            Duplexing = _twoPages ? Duplexing.TwoSidedLongEdge : Duplexing.OneSided,
            PageOrientation = IsLandscape(_front ?? _back) ? PageOrientation.Landscape : PageOrientation.Portrait,
        };
        var validated = queue.MergeAndValidatePrintTicket(queue.UserPrintTicket, delta);

        string xml = PrintTicketXml.Prefix;
        xml += _job.RotateFront ? PrintTicketXml.FlipFrontFlipped : PrintTicketXml.FlipFrontNone;
        xml += _job.DisablePrinting switch
        {
            "all" => PrintTicketXml.DisablePrintingAll,
            "front" => PrintTicketXml.DisablePrintingFront,
            "back" => PrintTicketXml.DisablePrintingBack,
            _ => PrintTicketXml.DisablePrintingOff,
        };
        if (_twoPages)
            xml += _job.RotateBack ? PrintTicketXml.FlipBackFlipped : PrintTicketXml.FlipBackNone;
        xml += TopcoatXml(_job.TopcoatFront, front: true);
        if (_twoPages)
            xml += TopcoatXml(_job.TopcoatBack, front: false);
        if (_hasK)
            xml += Feature("DocumentPrintBlackImagePixelsUsingMonochrome", "ON");
        // Modo de impresión: custom fija los dpi de color y de monocromo (300x600 / 300x1200 = texto más nítido).
        string mode = (_job.PrintMode ?? "").ToLowerInvariant();
        if (mode is "standard" or "best" or "custom")
            xml += Feature("JobPrintMode", mode == "best" ? "BestPossible" : mode == "custom" ? "Custom" : "Standard");
        if (mode == "custom")
        {
            if (_job.ColorDpi is "300x300" or "300x600")
                xml += Feature("JobPrintModeCustomColorDpi", "_" + _job.ColorDpi);
            if (_job.MonoDpi is "300x300" or "300x600" or "300x1200")
                xml += Feature("JobPrintModeCustomMonochromeDpi", "_" + _job.MonoDpi);
        }
        // Split ribbon: una sola tanda de paneles de la cinta para las dos caras (frente color, reverso solo K).
        xml += (_job.SplitRibbon ?? "").ToLowerInvariant() switch
        {
            "ymct_k" => Feature("JobSplitRibbonPanels", "YMCT_front_K_back"),
            "ymc_kt" => Feature("JobSplitRibbonPanels", "YMC_front_KT_back"),
            _ => "",
        };
        xml += _job.ColorMode switch
        {
            "icc" => Feature("DocumentColorMode", "ICCWorkFlow"),
            "vivid" => Feature("DocumentColorMode", "VividWorkFlow"),
            _ => "",
        };
        xml += PrintTicketXml.Suffix;

        var xd = new XmlDocument();
        xd.LoadXml(xml);
        var ms = new MemoryStream();
        xd.Save(ms);
        ms.Position = 0;
        var ticket = queue.MergeAndValidatePrintTicket(validated.ValidatedPrintTicket, new PrintTicket(ms)).ValidatedPrintTicket;

        if (_job.TicketApply != "devmode")
        {
            // Probado con la DS3 (tarjetas 2484/2485): fija las Preferencias de impresión.
            // La vía DEVMODE (solo este trabajo) imprimió la tarjeta 2486 ampliada;
            // queda como opción --ticket devmode hasta verificarla.
            queue.UserPrintTicket = ticket;
            queue.Commit();
            TicketMode = "commit";
            return;
        }
        try
        {
            // Solo este trabajo: Print Ticket → DEVMODE → PrinterSettings.
            using var conv = new PrintTicketConverter(PrinterSettings.PrinterName, PrintTicketConverter.MaxPrintSchemaVersion);
            byte[] devmode = conv.ConvertPrintTicketToDevMode(ticket, BaseDevModeType.UserDefault);
            IntPtr h = Marshal.AllocHGlobal(devmode.Length);
            try
            {
                Marshal.Copy(devmode, 0, h, devmode.Length);
                PrinterSettings.SetHdevmode(h);
                DefaultPageSettings.SetHdevmode(h);
            }
            finally { Marshal.FreeHGlobal(h); }
            TicketMode = "devmode";
        }
        catch (Exception e)
        {
            // Como el ejemplo del SDK: fija las Preferencias de impresión del driver.
            Console.WriteLine("DEVMODE no disponible, se usa Commit(): " + e.Message);
            queue.UserPrintTicket = ticket;
            queue.Commit();
            TicketMode = "commit";
        }
    }

    private static string Feature(string name, string option) =>
        $"<psf:Feature name=\"ns0000:{name}\"><psf:Option name=\"ns0000:{option}\" /></psf:Feature>";

    private static string TopcoatXml(string mode, bool front)
    {
        string except = front ? PrintTicketXml.FrontTopcoatBlockingPreset_Except : PrintTicketXml.BackTopcoatBlockingPreset_Except;
        return (mode ?? "").ToLowerInvariant() switch
        {
            "all" => front ? PrintTicketXml.FrontTopcoatBlockingPreset_All : PrintTicketXml.BackTopcoatBlockingPreset_All,
            "chip" => except + (front ? PrintTicketXml.FrontTopcoatBlockingPreset_ISO_7816 : PrintTicketXml.BackTopcoatBlockingPreset_ISO_7816),
            "mag2" => except + (front ? PrintTicketXml.FrontTopcoatBlockingPreset_ISO_2Track : PrintTicketXml.BackTopcoatBlockingPreset_ISO_2Track),
            "mag3" => except + (front ? PrintTicketXml.FrontTopcoatBlockingPreset_ISO_3Track : PrintTicketXml.BackTopcoatBlockingPreset_ISO_3Track),
            "magjis" => except + (front ? PrintTicketXml.FrontTopcoatBlockingPreset_JIS : PrintTicketXml.BackTopcoatBlockingPreset_JIS),
            _ => "",
        };
    }

    // ---------- Impresión ----------

    protected override void OnBeginPrint(PrintEventArgs e)
    {
        base.OnBeginPrint(e);
        _page = 0;
    }

    protected override void OnQueryPageSettings(QueryPageSettingsEventArgs e)
    {
        base.OnQueryPageSettings(e);
        e.PageSettings.Landscape = IsLandscape(_page == 0 ? (_front ?? _back) : _back);
    }

    /// <summary>Último dibujo: tamaño de imagen, página en píxeles y si fue 1:1.</summary>
    public string DrawInfo { get; private set; } = "";

    protected override void OnPrintPage(PrintPageEventArgs e)
    {
        base.OnPrintPage(e);
        Bitmap img = _page == 0 ? _front : _back;
        if (img != null)
        {
            var g = e.Graphics;
            // Página física en píxeles del dispositivo (antes de cambiar unidades).
            float dpiX = g.DpiX;
            var (pageW, pageH, offX, offY) = EntrustCaps.PhysicalPage(g);
            // Unidad Document = 1/300": a 300 ppp coincide con el píxel del dispositivo.
            // (GraphicsUnit.Pixel en un DC de impresora NO es el píxel del dispositivo:
            // la tarjeta 2486 salió ampliada por eso.)
            g.PageUnit = GraphicsUnit.Document;
            float k = 300f / dpiX;   // píxeles del dispositivo → unidades Document
            pageW = (int)Math.Round(pageW * k);
            pageH = (int)Math.Round(pageH * k);
            g.TranslateTransform(-offX * k, -offY * k);

            bool native = Math.Abs(img.Width - pageW) <= 2 && Math.Abs(img.Height - pageH) <= 2;
            if (native)
            {
                g.InterpolationMode = InterpolationMode.NearestNeighbor;
                g.PixelOffsetMode = PixelOffsetMode.Half;
                g.DrawImage(img, new Rectangle(0, 0, img.Width, img.Height));
            }
            else
            {
                g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                g.PixelOffsetMode = PixelOffsetMode.HighQuality;
                g.DrawImage(img, new Rectangle(0, 0, pageW, pageH));
            }
            DrawInfo += $"{(_page == 0 ? "front" : "back")}:{img.Width}x{img.Height}->{pageW}x{pageH}@{dpiX}{(native ? " 1:1" : " escalado")} ";
        }
        _page++;
        e.HasMorePages = _twoPages && _page == 1;
    }

    /// <summary>
    /// Prueba sin impresora física: aplica el Print Ticket (DEVMODE), dibuja con el DC
    /// de vista previa del driver y guarda las caras compuestas (color + K) en outDir.
    /// No usa IBidiSpl ni toma tarjetas.
    /// </summary>
    public static System.Collections.Generic.Dictionary<string, object> DryRun(EntrustPrintJob job, string outDir)
    {
        var opts = new PrinterOptionsValues { _colorPrintResolution = "300x300" };
        var preview = new PreviewPrintController();
        using var doc = new EntrustCardDocument(job, opts) { PrintController = preview };
        doc.Print();
        if (!string.IsNullOrEmpty(outDir))
        {
            Directory.CreateDirectory(outDir);
            doc._front?.Save(Path.Combine(outDir, "front-composed.png"), ImageFormat.Png);
            doc._back?.Save(Path.Combine(outDir, "back-composed.png"), ImageFormat.Png);
            // Cada página tal como la recibe el driver (metarchivo) rasterizada al
            // tamaño físico a 300 ppp: si la tarjeta cabe entera, la escala es correcta.
            var pages = preview.GetPreviewPageInfo();
            for (int i = 0; i < pages.Length; i++)
            {
                var size = pages[i].PhysicalSize;   // 1/100"
                using var bmp = new Bitmap((int)Math.Round(size.Width * 3.0), (int)Math.Round(size.Height * 3.0));
                using (var g = Graphics.FromImage(bmp))
                {
                    g.Clear(Color.White);
                    g.DrawImage(pages[i].Image, new Rectangle(0, 0, bmp.Width, bmp.Height));
                }
                bmp.Save(Path.Combine(outDir, $"preview-page{i + 1}.png"), ImageFormat.Png);
            }
        }
        return new System.Collections.Generic.Dictionary<string, object>
        {
            ["ok"] = true, ["dryRun"] = true, ["ticket"] = doc.TicketMode, ["draw"] = doc.DrawInfo.Trim(),
        };
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _front?.Dispose();
            _back?.Dispose();
        }
        base.Dispose(disposing);
    }
}
