using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.Versioning;
using CarnetPrintService.Api;
using CarnetPrintService.Printing;

namespace CarnetPrintService.Rendering;

/// <summary>
/// Convierte los PNG que manda el navegador en mapas de bits del tamaño exacto
/// de una tarjeta CR80 a 300 ppp.
///
/// El navegador manda la imagen tal como la rasterizó; aquí se normaliza a
/// 1012 x 638 px pase lo que pase, para que la impresión no dependa del zoom
/// del navegador, de la pantalla ni de la versión de Chrome.
/// </summary>
[SupportedOSPlatform("windows")]
public static class CardRenderer
{
    private const int MaxDataUrlChars = 24 * 1024 * 1024; // ~18 MB de PNG

    public static CardImages FromRequest(PrintRequest req)
    {
        var front = Decode(req.Front, "frente");
        Bitmap? back = null;
        if (!string.IsNullOrWhiteSpace(req.Back))
        {
            try { back = Decode(req.Back!, "reverso"); }
            catch { front.Dispose(); throw; }
        }
        return new CardImages { Front = front, Back = back };
    }

    private static Bitmap Decode(string dataUrl, string cara)
    {
        if (string.IsNullOrWhiteSpace(dataUrl))
            throw new ArgumentException($"Falta la imagen del {cara}.");
        if (dataUrl.Length > MaxDataUrlChars)
            throw new ArgumentException($"La imagen del {cara} es demasiado grande.");

        int comma = dataUrl.IndexOf(',');
        string b64 = comma >= 0 ? dataUrl[(comma + 1)..] : dataUrl;

        byte[] bytes;
        try { bytes = Convert.FromBase64String(b64); }
        catch { throw new ArgumentException($"La imagen del {cara} no es base64 válido."); }

        using var ms = new MemoryStream(bytes);
        using var src = new Bitmap(ms);
        return Normalize(src);
    }

    /// <summary>Lleva cualquier imagen al lienzo exacto de la tarjeta, sin deformarla.</summary>
    private static Bitmap Normalize(Bitmap src)
    {
        int w = Cr80.WidthPx, h = Cr80.HeightPx;
        var dst = new Bitmap(w, h, PixelFormat.Format24bppRgb);
        dst.SetResolution(Cr80.Dpi, Cr80.Dpi);

        using var g = Graphics.FromImage(dst);
        g.Clear(Color.White);
        g.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic;
        g.PixelOffsetMode = System.Drawing.Drawing2D.PixelOffsetMode.HighQuality;
        g.CompositingQuality = System.Drawing.Drawing2D.CompositingQuality.HighQuality;

        // La proporción de CR80 es fija; si la fuente no coincide, se centra y
        // se recorta lo mínimo en vez de estirar la tarjeta.
        double srcAr = (double)src.Width / src.Height;
        double dstAr = (double)w / h;
        RectangleF srcRect;
        if (Math.Abs(srcAr - dstAr) < 0.005)
        {
            srcRect = new RectangleF(0, 0, src.Width, src.Height);
        }
        else if (srcAr > dstAr)
        {
            float cw = (float)(src.Height * dstAr);
            srcRect = new RectangleF((src.Width - cw) / 2f, 0, cw, src.Height);
        }
        else
        {
            float ch = (float)(src.Width / dstAr);
            srcRect = new RectangleF(0, (src.Height - ch) / 2f, src.Width, ch);
        }

        g.DrawImage(src, new RectangleF(0, 0, w, h), srcRect, GraphicsUnit.Pixel);
        return dst;
    }
}
