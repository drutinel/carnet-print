using System.Text.Json.Serialization;

namespace CarnetPrintService.Api;

/// <summary>Geometría CR80 y resolución de trabajo. Única fuente de verdad del tamaño.</summary>
public static class Cr80
{
    public const double WidthMm = 85.6;
    public const double HeightMm = 54.0;
    public const int Dpi = 300;

    /// <summary>1012 px a 300 ppp.</summary>
    public static int WidthPx => (int)Math.Round(WidthMm / 25.4 * Dpi);
    /// <summary>638 px a 300 ppp.</summary>
    public static int HeightPx => (int)Math.Round(HeightMm / 25.4 * Dpi);

    /// <summary>Centésimas de pulgada, que es lo que espera PaperSize de System.Drawing.</summary>
    public static int WidthHundredthsInch => (int)Math.Round(WidthMm / 25.4 * 100);
    public static int HeightHundredthsInch => (int)Math.Round(HeightMm / 25.4 * 100);
}

public sealed class MagstripeData
{
    [JsonPropertyName("track1")] public string? Track1 { get; set; }
    [JsonPropertyName("track2")] public string? Track2 { get; set; }
    [JsonPropertyName("track3")] public string? Track3 { get; set; }

    public bool IsEmpty =>
        string.IsNullOrWhiteSpace(Track1) &&
        string.IsNullOrWhiteSpace(Track2) &&
        string.IsNullOrWhiteSpace(Track3);
}

public sealed class PrintOptions
{
    /// <summary>Imprimir las dos caras en un solo trabajo. Requiere equipo dúplex.</summary>
    [JsonPropertyName("duplex")] public bool Duplex { get; set; } = true;

    /// <summary>Girar el reverso 180°, para equipos que lo sacan de cabeza.</summary>
    [JsonPropertyName("rotateBack")] public bool RotateBack { get; set; }

    /// <summary>Corrimiento fino en milímetros. Normalmente 0: el servicio posiciona por geometría.</summary>
    [JsonPropertyName("offsetXmm")] public double OffsetXmm { get; set; }
    [JsonPropertyName("offsetYmm")] public double OffsetYmm { get; set; }

    [JsonPropertyName("copies")] public int Copies { get; set; } = 1;

    /// <summary>"full" | "none" | "custom". Solo lo aplica el driver que lo soporte.</summary>
    [JsonPropertyName("topcoat")] public string Topcoat { get; set; } = "full";

    [JsonPropertyName("magstripe")] public MagstripeData? Magstripe { get; set; }
}

public sealed class PrintRequest
{
    [JsonPropertyName("printerId")] public string PrinterId { get; set; } = "";

    /// <summary>Número de control del carnet, para rastrear el trabajo.</summary>
    [JsonPropertyName("control")] public string? Control { get; set; }

    /// <summary>PNG en data URL, 1012 x 638 px. Obligatorio.</summary>
    [JsonPropertyName("front")] public string Front { get; set; } = "";

    /// <summary>PNG en data URL. Opcional: sin él se imprime una sola cara.</summary>
    [JsonPropertyName("back")] public string? Back { get; set; }

    [JsonPropertyName("options")] public PrintOptions Options { get; set; } = new();
}

public sealed class PrinterCapabilities
{
    [JsonPropertyName("duplex")] public bool Duplex { get; set; }
    [JsonPropertyName("magstripe")] public bool Magstripe { get; set; }
    [JsonPropertyName("topcoat")] public bool Topcoat { get; set; }
    [JsonPropertyName("uvPanel")] public bool UvPanel { get; set; }
    [JsonPropertyName("lamination")] public bool Lamination { get; set; }
}

public sealed class PrinterInfo
{
    [JsonPropertyName("id")] public string Id { get; set; } = "";
    [JsonPropertyName("name")] public string Name { get; set; } = "";
    [JsonPropertyName("driver")] public string Driver { get; set; } = "";
    [JsonPropertyName("windowsName")] public string WindowsName { get; set; } = "";

    /// <summary>false cuando el SDK o la impresora no están presentes.</summary>
    [JsonPropertyName("available")] public bool Available { get; set; }

    /// <summary>Por qué no está disponible, en palabras que el operador entienda.</summary>
    [JsonPropertyName("reason")] public string? Reason { get; set; }

    [JsonPropertyName("capabilities")] public PrinterCapabilities Capabilities { get; set; } = new();
}

public enum JobState { Queued, Printing, Done, Error }

public sealed class JobStatus
{
    [JsonPropertyName("jobId")] public string JobId { get; set; } = "";
    [JsonPropertyName("printerId")] public string PrinterId { get; set; } = "";
    [JsonPropertyName("control")] public string? Control { get; set; }

    [JsonPropertyName("state")]
    [JsonConverter(typeof(JsonStringEnumConverter))]
    public JobState State { get; set; } = JobState.Queued;

    [JsonPropertyName("message")] public string? Message { get; set; }
    [JsonPropertyName("createdAt")] public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.Now;
    [JsonPropertyName("finishedAt")] public DateTimeOffset? FinishedAt { get; set; }
}

public sealed class HealthResponse
{
    [JsonPropertyName("ok")] public bool Ok { get; set; } = true;
    [JsonPropertyName("service")] public string Service { get; set; } = "CarnetPrintService";
    [JsonPropertyName("version")] public string Version { get; set; } = "1.0.0";
    [JsonPropertyName("cardWidthPx")] public int CardWidthPx { get; set; } = Cr80.WidthPx;
    [JsonPropertyName("cardHeightPx")] public int CardHeightPx { get; set; } = Cr80.HeightPx;
    [JsonPropertyName("dpi")] public int Dpi { get; set; } = Cr80.Dpi;
}
