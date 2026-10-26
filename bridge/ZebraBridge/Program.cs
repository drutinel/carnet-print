// ZebraBridge — puente entre el middleware (Python) y el Link-OS Card SDK de
// Zebra (ZC100/ZC300). Misma convención que CardBridge (Entrust): una
// invocación = una operación, respuesta JSON en una línea por stdout, todo lo
// demás a stderr.
//
//   ZebraBridge discover
//   ZebraBridge status [--usb DIRECCION]
//   ZebraBridge print  --front f.png [--back b.png] [--front-k fk.png] [--back-k bk.png]
//                      [--usb DIRECCION]
//                      [--back-type color|mono|none] [--overlay-front true|false]
//                      [--overlay-back true|false] [--source feeder|internal|atm]
//                      [--no-wait] [--timeout 240] [--recover-wait 120]
//                      [--copies N]  (varias tarjetas en un solo trabajo del SDK)
//                      [--auto-k]    (sin capa K: separa el negro del color con el SDK)
//                      [--front-special f.png --special-type pearl|silver|white]
//                      [--overlay-front-mask m.png] [--overlay-back-mask m.png]
//                      [--dry-run --out DIR]  (prepara los paneles y los guarda; sin USB)
//
// --printer se acepta (nombre de Windows) pero la conexión es USB directa por el
// SDK; sin --usb se usa la única ZC conectada.
//
// Código de salida: 0 bien, 1 error de la impresora o del trabajo, 2 uso,
// 3 tiempo agotado.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading;
using Zebra.Sdk.Card.Containers;
using Zebra.Sdk.Card.Enumerations;
using Zebra.Sdk.Card.Graphics;
using Zebra.Sdk.Card.Graphics.Enumerations;
using Zebra.Sdk.Card.Job;
using Zebra.Sdk.Card.Printer;
using Zebra.Sdk.Card.Printer.Discovery;
using Zebra.Sdk.Comm;
using Zebra.Sdk.Printer.Discovery;

namespace ZebraBridge
{
    internal static class Program
    {
        private static TextWriter _stdout;
        private static int _resultWritten;

        [STAThread]
        private static int Main(string[] args)
        {
            _stdout = Console.Out;
            Console.SetOut(Console.Error);

            if (args.Length == 0)
                return Fail(2, "uso: ZebraBridge discover|status|print ...");

            Args a;
            try { a = Args.Parse(args); }
            catch (ArgumentException e) { return Fail(2, e.Message); }

            int timeout = a.Int("timeout", a.Command == "print" ? 240 : 30);
            var watchdog = new Timer(_ =>
            {
                Fail(3, $"tiempo agotado ({timeout}s) esperando a la impresora");
                Environment.Exit(3);
            }, null, timeout * 1000, System.Threading.Timeout.Infinite);

            try
            {
                switch (a.Command)
                {
                    case "discover": return Discover();
                    case "status": return WithPrinter(a, Status);
                    case "print":
                        return a.Flag("dry-run") ? DryRun(a) : WithPrinter(a, p => Print(p, a));
                    default: return Fail(2, $"comando desconocido: {a.Command}");
                }
            }
            catch (Exception e)
            {
                return Fail(1, e.Message);
            }
            finally
            {
                watchdog.Dispose();
            }
        }

        private static int Discover()
        {
            var found = UsbDiscoverer.GetZebraUsbPrinters(new ZebraCardPrinterFilter());
            var all = UsbDiscoverer.GetZebraUsbPrinters();
            var drivers = UsbDiscoverer.GetZebraDriverPrinters();
            return Ok(new Dictionary<string, object>
            {
                ["printers"] = found.Select(p => p.Address).ToList(),
                ["allUsb"] = all.Select(p => p.Address).ToList(),
                ["drivers"] = drivers.Select(p => p.Address + " | " + string.Join(";", p.DiscoveryDataMap.Select(kv => kv.Key + "=" + kv.Value))).ToList(),
            });
        }

        private static int WithPrinter(Args a, Func<ZebraCardPrinter, int> body)
        {
            string address = a.Str("usb");
            bool cached = false;
            if (string.IsNullOrEmpty(address))
            {
                // Dirección USB de la última vez: evita el descubrimiento en cada tarjeta.
                address = UsbCache.Read();
                cached = !string.IsNullOrEmpty(address);
            }
            if (string.IsNullOrEmpty(address))
            {
                var found = UsbDiscoverer.GetZebraUsbPrinters(new ZebraCardPrinterFilter());
                if (found.Count == 0) return Fail(1, "no hay ninguna impresora Zebra de tarjetas conectada por USB");
                if (found.Count > 1) return Fail(1, "hay varias Zebra conectadas; indica --usb (ver 'discover')");
                address = found[0].Address;
            }

            Connection connection = new UsbConnection(address);
            ZebraCardPrinter printer = null;
            try
            {
                try { connection.Open(); }
                catch when (cached)
                {
                    // La dirección guardada ya no sirve (otro puerto USB): se redescubre.
                    UsbCache.Clear();
                    return WithPrinter(a, body);
                }
                UsbCache.Write(address);
                printer = ZebraCardPrinterFactory.GetInstance(connection);
                return body(printer);
            }
            finally
            {
                try { printer?.Destroy(); } catch { }
                try { connection.Close(); } catch { }
            }
        }

        private static int Status(ZebraCardPrinter p)
        {
            var info = p.GetPrinterInformation();
            var st = p.GetPrinterStatus();
            var media = p.GetMediaInformation();
            var body = new Dictionary<string, object>
            {
                ["model"] = info.Model,
                ["serial"] = info.SerialNumber,
                ["firmware"] = info.FirmwareVersion,
                ["printerStatus"] = st.Status,
                ["ready"] = string.Equals(st.Status, "idle", StringComparison.OrdinalIgnoreCase)
                            && (st.ErrorInfo?.Value ?? 0) == 0,
                ["jobsPending"] = st.JobsPending,
                ["jobsActive"] = st.JobsActive,
                ["printCapability"] = p.GetPrintCapability().ToString(),
                ["laminator"] = p.HasLaminator(),
                ["magEncoder"] = p.HasMagneticEncoder(),
                ["smartCardEncoder"] = p.HasSmartCardEncoder(),
                ["media"] = media.Select(m => new Dictionary<string, object>
                {
                    ["type"] = m.Type.ToString(),
                    ["description"] = m.Description,
                    ["partNumber"] = m.PartNumber,
                    ["panelsRemaining"] = m.PanelsRemaining,
                    ["initialSize"] = m.InitialSize,
                }).ToList(),
            };
            if ((st.ErrorInfo?.Value ?? 0) != 0)
                body["error"] = $"{st.ErrorInfo.Value} {st.ErrorInfo.Description}";
            if ((st.AlarmInfo?.Value ?? 0) != 0)
                body["alarm"] = $"{st.AlarmInfo.Value} {st.AlarmInfo.Description}";
            return Ok(body);
        }

        private static int Print(ZebraCardPrinter p, Args a)
        {
            string err = CheckFiles(a);
            if (err != null) return Fail(2, err);

            var draw = new List<string>();
            List<GraphicsInfo> graphicsData;
            using (var g = new ZebraCardGraphics(p))
                graphicsData = BuildGraphics(g, a, draw);

            string source = (a.Str("source") ?? "feeder").ToLowerInvariant();
            p.SetJobSetting(ZebraCardJobSettingNames.CARD_SOURCE,
                source == "internal" ? "Internal" : source == "atm" ? "ATM" : "Feeder");
            p.SetJobSetting(ZebraCardJobSettingNames.CARD_DESTINATION, "Eject");

            int copies = Math.Max(1, Math.Min(10, a.Int("copies", 1)));
            int jobId = p.Print(copies, graphicsData);
            var result = new Dictionary<string, object>
            {
                ["printerJobId"] = jobId, ["copies"] = copies, ["draw"] = string.Join(" ", draw),
            };
            if (a.Flag("no-wait"))
            {
                result["state"] = "submitted";
                return Ok(result);
            }
            return Poll(p, jobId, result, new ZebraRecovery(a.Int("recover-wait", 120)));
        }

        // Lienzo nativo de la ZC300 a 300 ppp (SDK: PrinterModel.ZC300 "Max Width = 1006
        // Max Height = 640"; ficha ZC300: "Image size 1006 x 640 pixels").
        private const int NativeW = 1006, NativeH = 640;

        /// <summary>
        /// Paneles del trabajo: por cara Color + MonoK (capa negra) + panel especial
        /// + Overlay. Sirve igual para imprimir y para --dry-run.
        /// </summary>
        private static List<GraphicsInfo> BuildGraphics(ZebraCardGraphics g, Args a, List<string> draw)
        {
            string front = a.Str("front"), back = a.Str("back");
            string frontK = a.Str("front-k"), backK = a.Str("back-k");
            string backType = (a.Str("back-type") ?? "color").ToLowerInvariant();
            bool overlayFront = a.Bool("overlay-front", true);
            bool overlayBack = a.Bool("overlay-back", true);
            bool autoK = a.Flag("auto-k");
            string special = a.Str("front-special");
            string specialType = (a.Str("special-type") ?? "").ToLowerInvariant();

            var list = new List<GraphicsInfo>();
            // Orden de la cinta YMCKO: color, luego K, luego overlay.
            if (!string.IsNullOrEmpty(front))
            {
                AddColorAndK(g, list, draw, CardSide.Front, front, frontK, autoK);
                if (!string.IsNullOrEmpty(special))
                {
                    PrintType t = specialType == "pearl" ? PrintType.Pearl
                                : specialType == "silver" ? PrintType.SilverResin
                                : specialType == "white" ? PrintType.WhiteResin
                                : throw new ArgumentException("--special-type debe ser pearl|silver|white");
                    list.Add(Side(g, CardSide.Front, t, File.ReadAllBytes(special), draw));
                }
                if (overlayFront) list.Add(Overlay(g, CardSide.Front, a.Str("overlay-front-mask"), draw));
            }
            if (!string.IsNullOrEmpty(back) && backType != "none")
            {
                if (backType == "mono")
                    // Reverso solo negro: la capa K si viene; si no, la imagen umbralizada.
                    list.Add(Side(g, CardSide.Back, PrintType.MonoK, File.ReadAllBytes(string.IsNullOrEmpty(backK) ? back : backK), draw));
                else
                    AddColorAndK(g, list, draw, CardSide.Back, back, backK, autoK);
                if (overlayBack) list.Add(Overlay(g, CardSide.Back, a.Str("overlay-back-mask"), draw));
            }
            return list;
        }

        private static void AddColorAndK(ZebraCardGraphics g, List<GraphicsInfo> list, List<string> draw,
            CardSide side, string colorPath, string kPath, bool autoK)
        {
            byte[] color = File.ReadAllBytes(colorPath);
            byte[] k = string.IsNullOrEmpty(kPath) ? null : File.ReadAllBytes(kPath);
            if (k == null && autoK)
            {
                // Sin capa K del generador: el SDK separa el negro (umbral 50 por canal)
                // para mandarlo al panel K en vez de negro compuesto.
                var ex = g.ExtractBlackImageData(color, 50, 50, 50);
                color = ex.ColorImageData;
                k = ex.MonoImageData;
            }
            list.Add(Side(g, side, PrintType.Color, color, draw));
            if (k != null) list.Add(Side(g, side, PrintType.MonoK, k, draw));
        }

        private static GraphicsInfo Side(ZebraCardGraphics g, CardSide side, PrintType type, byte[] data, List<string> draw)
        {
            int iw, ih;
            using (var ms = new MemoryStream(data))
            using (var img = System.Drawing.Image.FromStream(ms, false, false))
            { iw = img.Width; ih = img.Height; }

            // DrawImage(w,h) es el rectángulo destino en píxeles del panel. Con 0 NO se
            // escala al panel: usa el tamaño propio de la imagen (doc ZebraGraphicsI.DrawImage),
            // y una imagen de otra medida saldría recortada. Siempre 1006×640: 1:1 si ya
            // mide eso, escalada si no.
            g.MonochromeConverionType = MonochromeConversion.None;   // capa K nítida, sin tramado
            g.Initialize(NativeW, NativeH, OrientationType.Landscape, type, System.Drawing.Color.White);
            g.DrawImage(data, 0, 0, NativeW, NativeH, RotationType.RotateNoneFlipNone);
            var image = g.CreateImage();
            g.Clear();
            bool native = iw == NativeW && ih == NativeH;
            draw.Add($"{side}/{type}:{iw}x{ih}->{NativeW}x{NativeH}{(native ? " 1:1" : " escalado")}");
            return new GraphicsInfo
            {
                Side = side,
                PrintType = type,
                GraphicType = GraphicType.BMP,
                GraphicData = image,
            };
        }

        /// <summary>Overlay completo, o solo donde la máscara es negra (1 bpp).</summary>
        private static GraphicsInfo Overlay(ZebraCardGraphics g, CardSide side, string maskPath, List<string> draw)
        {
            if (string.IsNullOrEmpty(maskPath)) return Overlay(side);
            return Side(g, side, PrintType.Overlay, File.ReadAllBytes(maskPath), draw);
        }

        /// <summary>
        /// --dry-run: valida argumentos y prepara los paneles igual que al imprimir, sin
        /// USB ni impresora (ZebraCardGraphics con PrinterModel.ZC300). Guarda cada panel
        /// como BMP en --out.
        /// </summary>
        private static int DryRun(Args a)
        {
            string err = CheckFiles(a);
            if (err != null) return Fail(2, err);
            var draw = new List<string>();
            List<GraphicsInfo> data;
            using (var g = new ZebraCardGraphics(null) { PrinterModel = PrinterModel.ZC300 })
                data = BuildGraphics(g, a, draw);

            var panels = new List<string>();
            string outDir = a.Str("out");
            if (!string.IsNullOrEmpty(outDir)) Directory.CreateDirectory(outDir);
            int i = 0;
            foreach (var gi in data)
            {
                string name = $"{++i}-{gi.Side}-{gi.PrintType}";
                panels.Add(name);
                if (!string.IsNullOrEmpty(outDir) && gi.GraphicData != null)
                    File.WriteAllBytes(Path.Combine(outDir, name + ".bmp"), gi.GraphicData.ImageData);
            }
            return Ok(new Dictionary<string, object>
            {
                ["dryRun"] = true, ["panels"] = panels, ["draw"] = string.Join(" ", draw),
                ["copies"] = Math.Max(1, Math.Min(10, a.Int("copies", 1))),
            });
        }

        private static string CheckFiles(Args a)
        {
            if (string.IsNullOrEmpty(a.Str("front")) && string.IsNullOrEmpty(a.Str("back")))
                return "falta --front y/o --back";
            foreach (var k in new[] { "front", "back", "front-k", "back-k", "front-special", "overlay-front-mask", "overlay-back-mask" })
            {
                string f = a.Str(k);
                if (!string.IsNullOrEmpty(f) && !File.Exists(f)) return $"no existe la imagen: {f}";
            }
            if (!string.IsNullOrEmpty(a.Str("front-special")) && string.IsNullOrEmpty(a.Str("special-type")))
                return "--front-special necesita --special-type pearl|silver|white";
            return null;
        }

        private static GraphicsInfo Overlay(CardSide side) => new GraphicsInfo
        {
            Side = side,
            PrintType = PrintType.Overlay,
            GraphicType = GraphicType.NA,
            GraphicData = null,
        };

        private static int Poll(ZebraCardPrinter p, int jobId, Dictionary<string, object> result, ZebraRecovery recovery)
        {
            while (true)
            {
                var js = p.GetJobStatus(jobId);
                string status = js.PrintStatus ?? "";
                result["jobState"] = status;
                if (recovery.Recoveries.Count > 0) result["recoveries"] = recovery.Recoveries;

                if (status.StartsWith("done_ok", StringComparison.OrdinalIgnoreCase))
                {
                    result["state"] = "printed";
                    return Ok(result);
                }
                if (status.Contains("error") || status.StartsWith("cancelled", StringComparison.OrdinalIgnoreCase))
                {
                    result["state"] = "error";
                    result["error"] = Describe(js) ?? status;
                    AddCode(result, js);
                    return Write(1, Failed(result));
                }
                if (((js.ErrorInfo?.Value ?? 0) != 0 || (js.AlarmInfo?.Value ?? 0) != 0) && !ZebraRecovery.IsNotice(js))
                {
                    // Alarma corregible (sin tarjetas, tapa abierta, cinta): se espera al
                    // operador y el trabajo sigue solo. Si no, se cancela.
                    if (recovery.Handle(p, jobId, js)) continue;

                    var last = p.GetJobStatus(jobId);
                    if ((last.ErrorInfo?.Value ?? 0) == 0 && (last.AlarmInfo?.Value ?? 0) == 0) last = js;
                    try { p.Cancel(jobId); } catch { }
                    result["state"] = "error";
                    result["error"] = Describe(last);
                    AddCode(result, last);
                    if (recovery.Attempted) result["recovered"] = false;
                    return Write(1, Failed(result));
                }
                Thread.Sleep(1000);
            }
        }

        private static string Describe(JobStatusInfo js)
        {
            if ((js.ErrorInfo?.Value ?? 0) != 0) return $"{js.ErrorInfo.Value} {js.ErrorInfo.Description}";
            if ((js.AlarmInfo?.Value ?? 0) != 0) return $"{js.AlarmInfo.Value} {js.AlarmInfo.Description}";
            return null;
        }

        private static void AddCode(Dictionary<string, object> result, JobStatusInfo js)
        {
            int code = (js.ErrorInfo?.Value ?? 0) != 0 ? js.ErrorInfo.Value : js.AlarmInfo?.Value ?? 0;
            if (code != 0) result["errorCode"] = code;
        }

        private static Dictionary<string, object> Failed(Dictionary<string, object> body)
        {
            body["ok"] = false;
            return body;
        }

        private static int Ok(Dictionary<string, object> body)
        {
            body["ok"] = true;
            return Write(0, body);
        }

        private static int Fail(int code, string message) =>
            Write(code, new Dictionary<string, object> { ["ok"] = false, ["error"] = message });

        private static int Write(int code, Dictionary<string, object> body)
        {
            if (Interlocked.Exchange(ref _resultWritten, 1) == 0)
            {
                _stdout.WriteLine(JsonSerializer.Serialize(body));
                _stdout.Flush();
            }
            return code;
        }
    }

    /// <summary>Última dirección USB de la ZC (en %LOCALAPPDATA%\ZebraBridge\usb.txt).</summary>
    internal static class UsbCache
    {
        private static readonly string FilePath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ZebraBridge", "usb.txt");

        public static string Read()
        {
            try { return File.Exists(FilePath) ? File.ReadAllText(FilePath).Trim() : null; }
            catch { return null; }
        }

        public static void Write(string address)
        {
            try { Directory.CreateDirectory(Path.GetDirectoryName(FilePath)); File.WriteAllText(FilePath, address); }
            catch { }
        }

        public static void Clear()
        {
            try { File.Delete(FilePath); } catch { }
        }
    }

    internal sealed class Args
    {
        public string Command { get; private set; }
        private readonly Dictionary<string, string> _values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        public static Args Parse(string[] argv)
        {
            var a = new Args { Command = argv[0].ToLowerInvariant() };
            for (int i = 1; i < argv.Length; i++)
            {
                string k = argv[i];
                if (!k.StartsWith("--")) throw new ArgumentException($"argumento inesperado: {k}");
                k = k.Substring(2);
                bool hasValue = i + 1 < argv.Length && !argv[i + 1].StartsWith("--");
                a._values[k] = hasValue ? argv[++i] : "true";
            }
            return a;
        }

        public string Str(string k) => _values.TryGetValue(k, out var v) ? v : null;
        public bool Flag(string k) => _values.TryGetValue(k, out var v) && v != "false";
        public bool Bool(string k, bool def) => _values.TryGetValue(k, out var v) ? v != "false" : def;
        public int Int(string k, int def) => int.TryParse(Str(k), out var n) ? n : def;
    }
}
