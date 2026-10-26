using System.Text.Json;

namespace CarnetPrintService.Printing;

/// <summary>
/// Las cadenas de escape que entiende el driver XPS de Entrust, cargadas desde
/// escapes.json en vez de empotradas en el código.
///
/// Se hace así a propósito: la guía de referencia del SDK documenta que existen
/// escapes de texto para topcoat, bloqueo de impresión, banda magnética y
/// grabado, pero la sintaxis exacta depende de la versión del driver. Escribir
/// aquí una cadena inventada produciría fallos silenciosos: el trabajo sale, la
/// tarjeta se imprime y la banda queda sin codificar.
///
/// Copia las cadenas de la sección de escapes de la guía 527250-003f a
/// escapes.json. Mientras estén vacías, el servicio rechaza los trabajos que
/// las necesiten con un mensaje claro, en lugar de imprimir mal.
/// </summary>
public sealed class EscapeTable
{
    private readonly Dictionary<string, string> _map;

    private EscapeTable(Dictionary<string, string> map) => _map = map;

    public static EscapeTable Load(string path, ILogger logger)
    {
        try
        {
            if (File.Exists(path))
            {
                var json = File.ReadAllText(path);
                var map = JsonSerializer.Deserialize<Dictionary<string, string>>(json)
                          ?? new Dictionary<string, string>();
                int defined = map.Count(kv => !string.IsNullOrWhiteSpace(kv.Value));
                logger.LogInformation("escapes.json cargado: {defined} de {total} escapes definidos.",
                    defined, map.Count);
                return new EscapeTable(map);
            }
            logger.LogWarning("No encontré {path}. Los escapes quedan sin definir.", path);
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "No pude leer {path}.", path);
        }
        return new EscapeTable(new Dictionary<string, string>());
    }

    private string Require(string key, string para)
    {
        if (_map.TryGetValue(key, out var v) && !string.IsNullOrWhiteSpace(v)) return v;
        throw new InvalidOperationException(
            $"Falta el escape «{key}» en escapes.json, que hace falta para {para}. " +
            "Cópialo de la guía de referencia del SDK de Entrust (527250-003f, sección de escapes).");
    }

    /// <summary>Escape de topcoat: "full", "none" o "custom".</summary>
    public string Topcoat(string mode) =>
        Require($"topcoat.{mode.ToLowerInvariant()}", "controlar el topcoat");

    /// <summary>Escape de codificación de una pista magnética. {0} es el dato.</summary>
    public string MagTrack(int track, string data) =>
        string.Format(Require($"magstripe.track{track}", $"codificar la pista {track}"), data);
}
