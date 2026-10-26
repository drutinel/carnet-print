import subprocess  # noqa: F401 - los tests lo parchean por este módulo
from dataclasses import replace

from .base import PrintRequest
from .bridge import BRIDGE_DIR, BridgeAdapter
from .errors import ZEBRA_MESSAGES

DEFAULT_BRIDGE = BRIDGE_DIR / "zbin" / "ZebraBridge.exe"


class ZebraSdkAdapter(BridgeAdapter):
    """Zebra ZC100/ZC300 por el Link-OS Card SDK (bridge/zbin/ZebraBridge.exe).

    Conexión USB directa del SDK (no el spooler): frente a color + capa K, reverso a
    color o negro (K), overlay por cara, y el trabajo queda "printed" cuando la
    impresora reporta done_ok. Lienzo nativo 1006×640 (dibujado 1:1).
    """

    vendor = "SDK de Zebra"
    job_prefix = "zebra"
    default_bridge = DEFAULT_BRIDGE
    error_messages = ZEBRA_MESSAGES
    flag_options = {
        "auto_k": "--auto-k",                # sin capa K: el SDK separa el negro al panel K
    }
    value_options = {
        "back_type": "--back-type",          # color | mono | none
        "overlay_front": "--overlay-front",  # true | false
        "overlay_back": "--overlay-back",
        "source": "--source",                # feeder | internal | atm
        "usb": "--usb",                      # dirección USB si hay varias ZC
        "_copies": "--copies",               # interno: copias en un solo trabajo
    }

    def submit(self, request: PrintRequest) -> str:
        # Todas las copias en un trabajo del SDK (Print(copies, …)): la impresora las
        # encadena sin esperar otro arranque del puente por tarjeta.
        if request.copies > 1:
            request = replace(
                request, copies=1, options={**request.options, "_copies": str(request.copies)}
            )
        return super().submit(request)
