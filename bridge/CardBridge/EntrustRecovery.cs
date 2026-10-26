using System;
using System.Collections.Generic;
using System.Threading;
using dxp01sdk;

namespace CardBridge;

/// <summary>
/// Recuperación de errores del trabajo en modo interactivo (SDK_Dev_Guide p.42-45):
///   severidad 1-2 → cancelar; 3 → la tarjeta se pierde, se cancela (reiniciar el
///   trabajo es reimprimir, lo decide el operador); 4 → recuperable para la tarjeta:
///   se espera a que el operador lo corrija en la impresora (ErrorCode vuelve a 0,
///   p.44) y, si no, se intenta Resume (acción 101, solo válida en severidad 4);
///   5 → aviso, no hace falta nada.
/// Siempre se actúa con el PrinterJobID propio, nunca con 0 (p.106).
/// </summary>
internal sealed class EntrustRecovery
{
    private const int ResumeGraceSeconds = 15;

    private readonly int _waitSeconds;
    public List<Dictionary<string, object>> Recoveries { get; } = new();
    /// <summary>Último error visto; es el que hay que reportar y cancelar si no se recupera.</summary>
    public PrinterStatusValues LastError { get; private set; }
    public bool Attempted { get; private set; }

    public EntrustRecovery(int waitSeconds) => _waitSeconds = Math.Max(0, waitSeconds);

    public static bool IsNotice(PrinterStatusValues e) => e._errorSeverity == 5;

    /// <summary>
    /// Trata un error del trabajo <paramref name="jobId"/>. true = seguir sondeando
    /// (se corrigió, o el trabajo ya terminó y el sondeo lo verá); false = cancelar.
    /// </summary>
    public bool Handle(BidiSplWrap bidi, int jobId, PrinterStatusValues error) => Handle(bidi, jobId, error, 0);

    private bool Handle(BidiSplWrap bidi, int jobId, PrinterStatusValues error, int depth)
    {
        LastError = error;
        if (IsNotice(error)) return true;
        // Varios errores seguidos en la misma tarjeta: se deja de insistir.
        if (error._errorSeverity != 4 || depth >= 3) return false;

        Attempted = true;
        Console.WriteLine($"esperando al operador: {error._errorCode} {error._errorString} (hasta {_waitSeconds}s)");

        if (WaitUntilCleared(bidi, jobId, error, _waitSeconds, out bool otherError))
        {
            Log(error, "operator");
            return true;
        }
        if (otherError) return Handle(bidi, jobId, LastError, depth + 1);

        // El operador no la limpió desde la pantalla: un único Resume con el código actual.
        Console.WriteLine($"intentando reanudar el trabajo {jobId} tras el error {error._errorCode}");
        bidi.SetPrinterData(strings.PRINTER_ACTION,
            string.Format(strings.PRINTER_ACTION_XML, (int)Actions.Resume, jobId, error._errorCode));
        if (WaitUntilCleared(bidi, jobId, error, ResumeGraceSeconds, out otherError))
        {
            Log(error, "resume");
            return true;
        }
        return otherError && Handle(bidi, jobId, LastError, depth + 1);
    }

    /// <summary>
    /// Sondea hasta que el error del trabajo desaparece, el trabajo termina o aparece
    /// otro error distinto (<paramref name="otherError"/>; queda en LastError).
    /// </summary>
    private bool WaitUntilCleared(BidiSplWrap bidi, int jobId, PrinterStatusValues error, int seconds, out bool otherError)
    {
        otherError = false;
        var deadline = DateTime.UtcNow.AddSeconds(seconds);
        while (DateTime.UtcNow < deadline)
        {
            Thread.Sleep(1000);

            var job = Util.ParseJobStatusXML(
                bidi.GetPrinterData(strings.JOB_STATUS, string.Format(strings.JOB_STATUS_XML, jobId)));
            if (job._jobState is strings.JOB_SUCCEEDED or strings.JOB_FAILED or strings.JOB_CANCELLED
                or strings.CARD_NOT_RETRIEVED or strings.JOB_NOT_AVAILABLE)
                return true;

            var msg = Util.ParsePrinterStatusXML(bidi.GetPrinterData(strings.PRINTER_MESSAGES));
            if (msg._errorCode == 0 || msg._printerJobID != jobId) return true;
            if (msg._errorCode != error._errorCode)
            {
                LastError = msg;
                otherError = true;
                return false;
            }
        }
        return false;
    }

    private void Log(PrinterStatusValues e, string action)
    {
        Console.WriteLine($"recuperado ({action}): {e._errorCode} {e._errorString}");
        Recoveries.Add(new Dictionary<string, object>
        {
            ["code"] = e._errorCode,
            ["message"] = e._errorString,
            ["action"] = action,
        });
    }
}
