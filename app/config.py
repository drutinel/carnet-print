from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .paths import app_dir


class PrinterConfig(BaseModel):
    id: str
    label: str
    adapter: str = "cups"
    queue: str | None = None  # adapter cups
    printer_name: str | None = None  # adapter windows
    sumatra_path: str | None = None  # adapter windows
    # adapters entrust-sdk / zebra-sdk (por defecto bridge/bin/CardBridge.exe / bridge/zbin/ZebraBridge.exe)
    bridge_path: str | None = None
    # opción CUPS -> valores permitidos (lista vacía = cualquier valor)
    allowed_options: dict[str, list[str]] = Field(default_factory=dict)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARDPRINT_", env_file=app_dir() / ".env", extra="ignore")

    api_key: str
    printers_file: Path = app_dir() / "printers.yaml"
    data_dir: Path = app_dir()  # templates.json y carnets.json
    max_upload_bytes: int = 5 * 1024 * 1024
    host: str = "127.0.0.1"
    port: int = 8787
    open_browser: bool = True
    cors_origins: list[str] = Field(default_factory=list)


def load_printers(path: Path) -> list[PrinterConfig]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    printers = [PrinterConfig(**p) for p in data.get("printers", [])]
    ids = [p.id for p in printers]
    if len(ids) != len(set(ids)):
        raise ValueError("IDs de impresora duplicados en el archivo de configuración")
    return printers
