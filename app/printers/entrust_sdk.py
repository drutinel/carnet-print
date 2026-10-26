import subprocess  # noqa: F401 - los tests lo parchean por este módulo

from .bridge import BRIDGE_DIR, BridgeAdapter
from .errors import ENTRUST_MESSAGES

DEFAULT_BRIDGE = BRIDGE_DIR / "bin" / "CardBridge.exe"


class EntrustSdkAdapter(BridgeAdapter):
    """Entrust Sigma DS3 por el SDK del driver XPS (bridge/CardBridge.exe).

    A diferencia del conector SumatraPDF, fija opciones por trabajo con Print Ticket
    (giro por cara, topcoat, desactivar una cara, tolva) y espera a que la impresora
    confirme que la tarjeta salió.
    """

    vendor = "SDK de Entrust"
    job_prefix = "entrust"
    default_bridge = DEFAULT_BRIDGE
    error_messages = ENTRUST_MESSAGES
    flag_options = {"rotate_front": "--rotate-front", "rotate_back": "--rotate-back"}
    value_options = {
        "topcoat_front": "--topcoat-front",
        "topcoat_back": "--topcoat-back",
        "disable_printing": "--disable-printing",
        "hopper": "--hopper",
        "color_mode": "--color-mode",
        "print_mode": "--print-mode",
        "color_dpi": "--color-dpi",
        "mono_dpi": "--mono-dpi",
        "split_ribbon": "--split-ribbon",
    }
