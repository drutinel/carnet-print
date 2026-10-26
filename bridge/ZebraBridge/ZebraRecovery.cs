using System;
using System.Collections.Generic;
using System.Threading;
using Zebra.Sdk.Card.Containers;
using Zebra.Sdk.Card.Errors;
using Zebra.Sdk.Card.Printer;

namespace ZebraBridge
{
    /// <summary>
    /// Alarmas de la ZC que el operador puede corregir sin perder la tarjeta: con
    /// una alarma la impresora deja el trabajo en espera y lo continúa sola cuando
    /// se corrige (cargar tarjetas, cerrar la tapa, cambiar la cinta...). Se espera
    /// hasta N segundos a que AlarmInfo vuelva a 0; si no, el trabajo se cancela.
    /// Los errores (ErrorInfo) y las alarmas que no están aquí (atascos, fallos de
    /// cabezal) se cancelan de inmediato. JobUtil.Resume solo aplica a trabajos
    /// retenidos (codificación de chip), no a alarmas, por eso no se usa.
    /// Códigos: Zebra.Sdk.Card.Errors.ZebraCardErrors.
    /// </summary>
    internal sealed class ZebraRecovery
    {
        private static readonly HashSet<int> Recoverable = new HashSet<int>
        {
            ZebraCardErrors.MEDIA_OUT_OF_CARDS,        // 4001
            ZebraCardErrors.MEDIA_CARD_NOT_DETECTED,   // 4014
            ZebraCardErrors.MEDIA_INSERT_CARD_TIMEOUT, // 4015
            ZebraCardErrors.MEDIA_CARD_FEEDER_EMPTY,   // 4016
            ZebraCardErrors.DONOR_OUT_OF_RIBBON,       // 5001
            ZebraCardErrors.ENGINE_DOOR_OPEN,          // 7008
            ZebraCardErrors.ENGINE_MEDIA_DRAWER_OPEN,  // 7027
            ZebraCardErrors.ENGINE_FEEDER_DOOR_OPEN,   // 7028
            ZebraCardErrors.ENGINE_REJECT_BIN_FULL,    // 7034
        };

        // Avisos que no detienen el trabajo.
        private static readonly HashSet<int> Notices = new HashSet<int>
        {
            ZebraCardErrors.DONOR_RIBBON_LOW,          // 5009
        };

        private readonly int _waitSeconds;
        public List<Dictionary<string, object>> Recoveries { get; } = new List<Dictionary<string, object>>();
        public bool Attempted { get; private set; }

        public ZebraRecovery(int waitSeconds) { _waitSeconds = Math.Max(0, waitSeconds); }

        public static bool IsNotice(JobStatusInfo js) =>
            (js.ErrorInfo?.Value ?? 0) == 0 && Notices.Contains(js.AlarmInfo?.Value ?? 0);

        /// <summary>true = la alarma se corrigió y el trabajo sigue; false = cancelar.</summary>
        public bool Handle(ZebraCardPrinter p, int jobId, JobStatusInfo js)
        {
            int error = js.ErrorInfo?.Value ?? 0;
            int alarm = js.AlarmInfo?.Value ?? 0;
            if (error != 0 || !Recoverable.Contains(alarm)) return false;

            Attempted = true;
            string text = js.AlarmInfo.Description;
            Console.WriteLine($"esperando al operador: {alarm} {text} (hasta {_waitSeconds}s)");

            var deadline = DateTime.UtcNow.AddSeconds(_waitSeconds);
            while (DateTime.UtcNow < deadline)
            {
                Thread.Sleep(1000);
                var now = p.GetJobStatus(jobId);
                if ((now.ErrorInfo?.Value ?? 0) != 0) return false;
                int a = now.AlarmInfo?.Value ?? 0;
                if (a == alarm) continue;
                if (a != 0 && !Notices.Contains(a))
                    return Handle(p, jobId, now);   // otra alarma distinta
                Console.WriteLine($"recuperado (operator): {alarm} {text}");
                Recoveries.Add(new Dictionary<string, object>
                {
                    ["code"] = alarm,
                    ["message"] = text,
                    ["action"] = "operator",
                });
                return true;
            }
            return false;
        }
    }
}
