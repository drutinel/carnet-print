from ..config import PrinterConfig
from .base import PrinterAdapter
from .entrust_sdk import EntrustSdkAdapter
from .mock import MockAdapter
from .zebra_sdk import ZebraSdkAdapter


def build_adapter(cfg: PrinterConfig) -> PrinterAdapter:
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
