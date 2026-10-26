using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Printing;
using System.IO;
using System.Printing;
using System.Threading;
using System.Xml;
using dxp01sdk;

namespace CardBridge;

/// <summary>
/// Un carnet por el SDK de Entrust, siguiendo el ejemplo samples/csharp/print:
/// BindDevice → comprobar estado → StartJob → PrintDocument con Print Ticket
/// → esperar el jobID de Windows → EndJob → sondear hasta que termina.
/// </summary>
internal sealed class EntrustPrintJob
{
    public string PrinterName;
    public string FrontPath;
    public string BackPath;
    public string FrontKPath;      // capa negra (panel K), opcional
    public string BackKPath;
    public string ColorMode = "";  // "" driver | icc | vivid
    public string TicketApply = "commit";  // commit (probado) | devmode (solo este trabajo, sin verificar)
    public string PrintMode = "";   // "" driver | standard | best | custom
    public string ColorDpi = "";    // custom: 300x300 | 300x600
    public string MonoDpi = "";     // custom: 300x300 | 300x600 | 300x1200
    public string SplitRibbon = ""; // "" no | ymct_k | ymc_kt
    public bool RotateFront;
    public bool RotateBack;
    public string TopcoatFront = "";   // "" = lo que tenga el driver
    public string TopcoatBack = "";
    public string DisablePrinting = "off";
    public string Hopper = "";
    public bool WaitForCompletion = true;
    public string DocumentName = "Carnet";
    public int RecoverWait = 120;      // s de espera al operador ante un error leve (severidad 4)

    public Dictionary<string, object> Run()
    {
        foreach (var p in new[] { FrontPath, BackPath, FrontKPath, BackKPath })
            if (!string.IsNullOrEmpty(p) && !File.Exists(p))
                throw new FileNotFoundException("no existe la imagen", p);

        var result = new Dictionary<string, object> { ["printer"] = PrinterName };
        var bidi = new BidiSplWrap();
        bidi.BindDevice(PrinterName);
        int printerJobId = 0;
        try
        {
            var options = Util.ParsePrinterOptionsXML(bidi.GetPrinterData(strings.PRINTER_OPTIONS2));
            if (options._printerStatus is not ("Ready" or "Busy"))
                throw new Exception($"la impresora no está lista: {options._printerStatus}");
            if (options._printHead != "Installed" && options._connectionProtocol != "Version1")
                throw new Exception("la impresora no tiene cabezal instalado");

            string hopperId = Util.GetInputHopper(options._optionInputHopper, Hopper);
            printerJobId = Util.StartJob(bidi, hopperId, "default");
            result["printerJobId"] = printerJobId;

            using (var doc = new EntrustCardDocument(this, options))
            {
                doc.Print();
                result["ticket"] = doc.TicketMode;
                result["draw"] = doc.DrawInfo.Trim();
            }

            int windowsJobId = Util.WaitForWindowsJobID(bidi, PrinterName);
            result["windowsJobId"] = windowsJobId;
            bidi.SetPrinterData(strings.ENDJOB);

            if (windowsJobId == 0)
            {
                var m = Util.ParsePrinterStatusXML(bidi.GetPrinterData(strings.PRINTER_MESSAGES));
                Util.CancelJob(bidi, printerJobId, m._errorCode);
                result["ok"] = false;
                result["state"] = "error";
                result["error"] = $"{m._errorCode} {m._errorString}".Trim();
                return result;
            }

            if (!WaitForCompletion)
            {
                result["ok"] = true;
                result["state"] = "submitted";
                return result;
            }

            return Poll(bidi, printerJobId, result, new EntrustRecovery(RecoverWait));
        }
        catch (BidiException e)
        {
            Util.CancelJob(bidi, e.PrinterJobID, e.ErrorCode);
            result["ok"] = false;
            result["state"] = "error";
            result["error"] = e.Message;
            return result;
        }
        catch
        {
            if (printerJobId != 0) Util.CancelJob(bidi, printerJobId, 0);
            throw;
        }
        finally
        {
            bidi.UnbindDevice();
        }
    }

    /// <summary>Como Util.PollForJobCompletion, pero devuelve el estado en vez de escribirlo.</summary>
    /// Los errores leves del trabajo (severidad 4) pasan por <see cref="EntrustRecovery"/>.
    private static Dictionary<string, object> Poll(BidiSplWrap bidi, int printerJobId, Dictionary<string, object> result,
        EntrustRecovery recovery)
    {
        while (true)
        {
            string jobXml = bidi.GetPrinterData(strings.JOB_STATUS, string.Format(strings.JOB_STATUS_XML, printerJobId));
            var job = Util.ParseJobStatusXML(jobXml);
            var msg = Util.ParsePrinterStatusXML(bidi.GetPrinterData(strings.PRINTER_MESSAGES));

            if (job._jobState is strings.JOB_SUCCEEDED or strings.JOB_FAILED or strings.JOB_CANCELLED
                or strings.CARD_NOT_RETRIEVED or strings.JOB_NOT_AVAILABLE)
            {
                bool ok = job._jobState == strings.JOB_SUCCEEDED;
                result["jobState"] = job._jobState;
                result["ok"] = ok;
                result["state"] = ok ? "printed" : "error";
                if (!ok && msg._errorCode != 0)
                {
                    result["error"] = $"{msg._errorCode} {msg._errorString}";
                    result["errorCode"] = msg._errorCode;
                    result["errorSeverity"] = msg._errorSeverity;
                }
                else if (!ok)
                    result["error"] = job._jobState;
                if (recovery.Recoveries.Count > 0) result["recoveries"] = recovery.Recoveries;
                return result;
            }

            if (msg._errorCode != 0 && msg._printerJobID == printerJobId)
            {
                // Severidad 4: se espera al operador / Resume; si se corrige, sigue el sondeo.
                if (recovery.Handle(bidi, printerJobId, msg)) continue;

                // No recuperable (o no se corrigió a tiempo): se cancela con el código actual
                // para no dejar la impresora esperando.
                var err = recovery.LastError ?? msg;
                Util.CancelJob(bidi, printerJobId, err._errorCode);
                result["jobState"] = job._jobState;
                result["ok"] = false;
                result["state"] = "error";
                result["error"] = $"{err._errorCode} {err._errorString} (severidad {err._errorSeverity})";
                result["errorCode"] = err._errorCode;
                result["errorSeverity"] = err._errorSeverity;
                if (recovery.Attempted) result["recovered"] = false;
                if (recovery.Recoveries.Count > 0) result["recoveries"] = recovery.Recoveries;
                return result;
            }

            Thread.Sleep(1000);
        }
    }
}
