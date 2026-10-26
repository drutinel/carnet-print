from ..config import PrinterConfig
from .base import PrinterAdapter
from .cups import CupsAdapter
from .entrust_sdk import EntrustSdkAdapter
from .mock import MockAdapter
from .windows import WindowsAdapter
from .zebra_sdk import ZebraSdkAdapter


def build_adapter(cfg: PrinterConfig) -> PrinterAdapter:
    if cfg.adapter == "cups":
        if not cfg.queue:
            raise ValueError(f"Impresora {cfg.id}: adapter 'cups' requiere 'queue'")
        return CupsAdapter(cfg.queue)
    if cfg.adapter == "windows":
        if not cfg.printer_name:
            raise ValueError(f"Impresora {cfg.id}: adapter 'windows' requiere 'printer_name'")
        return WindowsAdapter(cfg.printer_name, cfg.sumatra_path)
    if cfg.adapter == "entrust-sdk":
        if not cfg.printer_name:
            raise ValueError(f"Impresora {cfg.id}: adapter 'entrust-sdk' requiere 'printer_name'")
        return EntrustSdkAdapter(cfg.printer_name, cfg.bridge_path)
    if cfg.adapter == "zebra-sdk":
        return ZebraSdkAdapter(cfg.printer_name or "ZC300", cfg.bridge_path)
    if cfg.adapter == "mock":
        return MockAdapter()
    raise ValueError(f"Impresora {cfg.id}: adapter desconocido '{cfg.adapter}'")


def build_registry(
    configs: list[PrinterConfig],
) -> dict[str, tuple[PrinterConfig, PrinterAdapter]]:
    return {c.id: (c, build_adapter(c)) for c in configs}
