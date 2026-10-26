"""Mensajes para el operador a partir del error que devuelve un puente de SDK.

Los puentes devuelven `error` (texto técnico del SDK, en inglés, p. ej. "112 Card hopper
empty") y, cuando lo saben, `errorCode`. Aquí se traduce a una instrucción en español y se
conserva el detalle técnico entre corchetes.
"""

import re

# SDK XPS de Entrust, apéndice A (SDK_Dev_Guide p.107-117).
ENTRUST_MESSAGES: dict[int, str] = {
    102: "La tarjeta no quedó en posición: abra la impresora, retire la tarjeta y reintente.",
    103: "Problema en la impresora: revise el mensaje en su pantalla.",
    104: "Problema crítico en la impresora: apáguela, enciéndala y reintente.",
    109: "Problema con la cinta: revise que esté bien instalada.",
    110: "Sin cinta o cinta agotada: cambie la cinta y reintente.",
    111: "No se pudo tomar la tarjeta: acomode las tarjetas en la tolva y reintente.",
    112: "Sin tarjetas en la tolva: cargue tarjetas y reintente.",
    113: "Tapa abierta: ciérrela para continuar.",
    114: "Se abrió la tapa durante la impresión: ciérrela y reintente.",
    118: "La cinta instalada no sirve para este trabajo.",
    119: "Cinta no compatible con esta impresora.",
    120: "La impresora está en pausa: reanúdela desde su pantalla.",
    121: "Cinta no identificada: retírela, vuelva a instalarla y reintente.",
    172: "La impresora pide una tarjeta de limpieza.",
    173: "La impresora se apagó mal: reiníciela y reintente.",
    243: "Se perdió una tarjeta dentro de la impresora: ábrala y retírela.",
    279: "Tipo de tarjeta no compatible.",
    294: "La impresora necesita limpieza.",
    500: "La impresora no está disponible: revise que esté encendida y conectada.",
    501: "Se perdió la conexión con la impresora: revise el cable USB.",
    505: "Problema de comunicación USB con la impresora.",
    506: "La impresora está ocupada con otra tarjeta: espere y reintente.",
    509: "La impresora está fuera de línea o en pausa en Windows.",
}

# Link-OS Card SDK de Zebra (Zebra.Sdk.Card.Errors.ZebraCardErrors).
_ZEBRA_JAM = "Atasco de tarjeta: abra la impresora, retire la tarjeta y reintente."
ZEBRA_MESSAGES: dict[int, str] = {
    4001: "Sin tarjetas en el alimentador: cargue tarjetas y reintente.",
    4016: "Sin tarjetas en el alimentador: cargue tarjetas y reintente.",
    4002: "Tipo de tarjeta no válido.",
    4003: _ZEBRA_JAM,
    4014: "No se detectó la tarjeta: revise el alimentador y reintente.",
    4015: "Se agotó el tiempo para insertar la tarjeta.",
    5001: "Sin cinta: cambie la cinta y reintente.",
    5002: "Cinta no válida para esta impresora.",
    5003: "Atasco de cinta: abra la impresora y revise la cinta.",
    5009: "La cinta está por agotarse.",
    7005: "Cabezal demasiado caliente: espere unos minutos y reintente.",
    7008: "Tapa abierta: ciérrela para continuar.",
    7024: _ZEBRA_JAM, 7025: _ZEBRA_JAM, 7026: _ZEBRA_JAM, 7036: _ZEBRA_JAM,
    7037: _ZEBRA_JAM, 7038: _ZEBRA_JAM, 7039: _ZEBRA_JAM,
    7027: "Cajón de tarjetas abierto: ciérrelo para continuar.",
    7028: "Tapa del alimentador abierta: ciérrela para continuar.",
    7034: "Bandeja de rechazo llena: vacíela y reintente.",
}

_CODE_RE = re.compile(r"\b(\d{3,5})\b")


def error_code(result: dict) -> int | None:
    """Código numérico del error: `errorCode` del puente o el primero que aparezca en el texto."""
    code = result.get("errorCode")
    if isinstance(code, int) and code:
        return code
    match = _CODE_RE.search(str(result.get("error") or ""))
    return int(match.group(1)) if match else None


def operator_message(vendor: str, messages: dict[int, str], result: dict) -> str:
    """Texto para el operador; el detalle técnico del SDK va entre corchetes al final."""
    detail = str(result.get("error") or "error desconocido").strip()
    code = error_code(result)
    text = messages.get(code) if code is not None else None
    if text is None:
        text = f"{vendor}: {detail}"
    else:
        text = f"{text} [{detail}]"
    if result.get("recovered") is False:
        text += " Se esperó a que se corrigiera en la impresora y no se resolvió a tiempo; la tarjeta se canceló."
    return text
