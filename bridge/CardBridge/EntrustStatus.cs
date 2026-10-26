using System;
using System.Collections.Generic;
using dxp01sdk;

namespace CardBridge;

/// <summary>Estado de la impresora leído por IBidiSpl (PrinterOptions2 + SuppliesStatus3).</summary>
internal static class EntrustStatus
{
    public static Dictionary<string, object> Read(BidiSplWrap bidi)
    {
        var o = Util.ParsePrinterOptionsXML(bidi.GetPrinterData(strings.PRINTER_OPTIONS2));
        var body = new Dictionary<string, object>
        {
            ["driverVersion"] = Util.ParseDriverVersionXML(bidi.GetPrinterData(strings.SDK_VERSION)),
            ["printerStatus"] = o._printerStatus,
            ["ready"] = o._printerStatus is "Ready" or "Busy",
            ["model"] = o._printerModel,
            ["serial"] = o._printerSerialNumber,
            ["firmware"] = o._printerVersion,
            ["printHead"] = o._printHead,
            ["colorResolution"] = o._colorPrintResolution,
            ["duplex"] = o._optionDuplex,
            ["inputHopper"] = o._optionInputHopper,
            ["magstripe"] = o._optionMagstripe,
            ["smartcard"] = o._optionSmartcard,
            ["laminator"] = o._laminator,
            ["locks"] = o._optionLocks,
            ["lockState"] = o._lockState,
            ["connection"] = o._connectionPortType,
        };

        try
        {
            var s = Util.ParseSuppliesXML(bidi.GetPrinterData(strings.SUPPLIES_STATUS3));
            body["ribbonType"] = s._printRibbonType;
            body["ribbonRemaining"] = s._ribbonRemaining;
            if (!string.IsNullOrEmpty(s._laminatorL1SerialNumber))
                body["laminatorL1Remaining"] = s._laminatorL1PercentRemaining;
            if (!string.IsNullOrEmpty(s._laminatorL2SerialNumber))
                body["laminatorL2Remaining"] = s._laminatorL2PercentRemaining;
        }
        catch (Exception e)
        {
            body["suppliesError"] = e.Message;
        }

        try
        {
            var m = Util.ParsePrinterStatusXML(bidi.GetPrinterData(strings.PRINTER_MESSAGES));
            if (m._errorCode != 0)
            {
                body["errorCode"] = m._errorCode;
                body["errorString"] = m._errorString;
                body["errorJobId"] = m._printerJobID;
            }
        }
        catch (Exception e)
        {
            body["messagesError"] = e.Message;
        }

        return body;
    }
}
