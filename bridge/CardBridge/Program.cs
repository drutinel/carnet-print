// CardBridge — puente entre el middleware (Python) y el SDK del driver XPS de
// Entrust. Una invocación = una operación. La respuesta va en JSON por stdout;
// todo lo que imprimen los fuentes del SDK (Console.WriteLine) se desvía a
// stderr para no ensuciar el JSON.
//
//   CardBridge status --printer "XPS Card Printer"
//   CardBridge print  --printer "XPS Card Printer" --front f.png [--back b.png]
//                     [--rotate-front] [--rotate-back]
//                     [--topcoat-front all|none|chip|mag2|mag3|magjis]
//                     [--topcoat-back  all|none|chip|mag2|mag3|magjis]
//                     [--disable-printing off|all|front|back]
//                     [--color-mode icc|vivid] [--print-mode standard|best|custom]
//                     [--color-dpi 300x300|300x600] [--mono-dpi 300x300|300x600|300x1200]
//                     [--split-ribbon ymct_k|ymc_kt]   (reverso solo K; una tanda de cinta)
//                     [--hopper 1] [--no-wait] [--doc-name nombre]
//                     [--timeout 180] [--recover-wait 120]
//
// Código de salida: 0 bien, 1 error de la impresora o del trabajo, 2 uso,
// 3 tiempo agotado.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Threading;
using dxp01sdk;

namespace CardBridge;

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
            return Fail(2, "uso: CardBridge status|print --printer NOMBRE ...");

        Args a;
        try { a = Args.Parse(args); }
        catch (ArgumentException e) { return Fail(2, e.Message); }

        if (string.IsNullOrWhiteSpace(a.Printer))
            return Fail(2, "falta --printer");

        // Las llamadas COM del SDK pueden quedarse colgadas si la impresora no
        // responde; un perro guardián corta el proceso con un JSON de error.
        int timeout = a.Int("timeout", a.Command == "print" ? 240 : 30);
        var watchdog = new Timer(_ =>
        {
            Fail(3, $"tiempo agotado ({timeout}s) esperando a la impresora");
            Environment.Exit(3);
        }, null, timeout * 1000, Timeout.Infinite);

        try
        {
            return a.Command switch
            {
                "status" => Status(a),
                "caps" => Ok(EntrustCaps.Read(a.Printer)),
                "print" => Print(a),
                _ => Fail(2, $"comando desconocido: {a.Command}")
            };
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

    private static int Status(Args a)
    {
        var bidi = new BidiSplWrap();
        bidi.BindDevice(a.Printer);
        try
        {
            var info = EntrustStatus.Read(bidi);
            return Ok(info);
        }
        finally
        {
            bidi.UnbindDevice();
        }
    }

    private static int Print(Args a)
    {
        var job = new EntrustPrintJob
        {
            PrinterName = a.Printer,
            FrontPath = a.Str("front"),
            BackPath = a.Str("back"),
            FrontKPath = a.Str("front-k"),
            BackKPath = a.Str("back-k"),
            ColorMode = (a.Str("color-mode") ?? "").ToLowerInvariant(),
            PrintMode = (a.Str("print-mode") ?? "").ToLowerInvariant(),
            ColorDpi = a.Str("color-dpi") ?? "",
            MonoDpi = a.Str("mono-dpi") ?? "",
            SplitRibbon = (a.Str("split-ribbon") ?? "").ToLowerInvariant(),
            TicketApply = (a.Str("ticket") ?? "commit").ToLowerInvariant(),
            RotateFront = a.Flag("rotate-front"),
            RotateBack = a.Flag("rotate-back"),
            TopcoatFront = a.Str("topcoat-front") ?? "",
            TopcoatBack = a.Str("topcoat-back") ?? "",
            DisablePrinting = a.Str("disable-printing") ?? "off",
            Hopper = a.Str("hopper") ?? "",
            WaitForCompletion = !a.Flag("no-wait"),
            DocumentName = a.Str("doc-name") ?? "Carnet",
            RecoverWait = a.Int("recover-wait", 120),
        };
        if (string.IsNullOrEmpty(job.FrontPath) && string.IsNullOrEmpty(job.BackPath))
            return Fail(2, "falta --front y/o --back");

        var result = a.Flag("dry-run") ? EntrustCardDocument.DryRun(job, a.Str("out")) : job.Run();
        return result.TryGetValue("ok", out var ok) && ok is true ? Ok(result) : Write(1, result);
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

internal sealed class Args
{
    public string Command { get; private set; }
    public string Printer => Str("printer");
    private readonly Dictionary<string, string> _values = new(StringComparer.OrdinalIgnoreCase);

    public static Args Parse(string[] argv)
    {
        var a = new Args { Command = argv[0].ToLowerInvariant() };
        for (int i = 1; i < argv.Length; i++)
        {
            string k = argv[i];
            if (!k.StartsWith("--")) throw new ArgumentException($"argumento inesperado: {k}");
            k = k[2..];
            bool hasValue = i + 1 < argv.Length && !argv[i + 1].StartsWith("--");
            a._values[k] = hasValue ? argv[++i] : "true";
        }
        return a;
    }

    public string Str(string k) => _values.TryGetValue(k, out var v) ? v : null;
    public bool Flag(string k) => _values.TryGetValue(k, out var v) && v != "false";
    public int Int(string k, int def) => int.TryParse(Str(k), out var n) ? n : def;
}
