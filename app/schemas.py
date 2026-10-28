"""Esquemas de entrada y salida del API: toda entrada JSON se valida aquí, con límites de tamaño."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from fastapi import Path as PathParam

# id de plantilla / cliente / número de control: se usan como clave en el JSON y en la URL
ItemId = Annotated[str, PathParam(pattern=r"^[\w\-. ]{1,64}$")]

ShortText = Annotated[str, StringConstraints(max_length=200)]
LongText = Annotated[str, StringConstraints(max_length=2000)]
# Solo imágenes en data URI y de hasta ~2,2 MB de binario (3 MB de base64)
ImageUri = Annotated[
    str, StringConstraints(max_length=3_000_000, pattern=r"^data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$")
]

KIOSK_FIELDS = ("name", "ced", "cat", "extra", "code", "issue", "photo")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TemplateFields(Strict):
    """Diseño de la plantilla: textos y medidas (las imágenes van aparte)."""

    org: ShortText = ""
    title: ShortText = ""
    band: ShortText = ""
    accent: ShortText = ""
    cardbg: ShortText = ""
    signname: ShortText = ""
    contact: ShortText = ""
    legend: LongText = ""
    valnum: ShortText = ""
    valunit: ShortText = ""
    prefix: ShortText = ""
    sealsize: ShortText = ""
    sealop: ShortText = ""
    sealsrc: ShortText = ""
    orgsize: ShortText = ""
    orgbold: ShortText = ""
    titlesize: ShortText = ""
    titlebold: ShortText = ""


class TemplateImages(Strict):
    logo1: ImageUri | None = None
    logo2: ImageUri | None = None
    seal: ImageUri | None = None
    sign: ImageUri | None = None


class TemplateIn(TemplateFields):
    name: ShortText = ""
    img: TemplateImages = Field(default_factory=TemplateImages)


class CardData(Strict):
    name: ShortText = ""
    ced: ShortText = ""
    code: ShortText = ""
    cat: ShortText = ""
    extra: ShortText = ""
    issue: ShortText = ""
    expiry: ShortText = ""


class CardImages(TemplateImages):
    photo: ImageUri | None = None


class CardIn(Strict):
    """Carnet nuevo: control, código, fecha y estado los pone el servidor."""

    tpl: TemplateFields
    data: CardData
    img: CardImages = Field(default_factory=CardImages)
    templateId: ShortText | None = None


class CardRestore(CardIn):
    """Carnet completo de un respaldo (conserva su control, fecha, reimpresiones y estado)."""

    control: ShortText = ""
    createdAt: int = Field(0, ge=0)
    prints: int = Field(1, ge=1)
    voided: bool = False


class CalIn(BaseModel):
    model_config = ConfigDict(extra="ignore")  # ajustes viejos traían claves que ya no existen
    rotate: bool = False
    split: bool = False
    ox: float = Field(0, ge=-20, le=20)
    oy: float = Field(0, ge=-20, le=20)


class SettingsIn(Strict):
    printer: Annotated[str, StringConstraints(max_length=64)] = ""
    quality: Literal["fine", "standard"] = "fine"
    hopper: Literal["", "1", "2", "3", "4", "5", "6"] = ""
    cal: dict[Annotated[str, StringConstraints(max_length=64)], CalIn] = Field(default_factory=dict, max_length=50)


class ClientIn(Strict):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    template_id: Annotated[str, StringConstraints(max_length=64)]
    editable: list[Literal["name", "ced", "cat", "extra", "code", "issue", "photo"]] = Field(default_factory=list)
    show_registry: bool = False


class PrinterOut(BaseModel):
    id: str
    label: str
    status: str  # ready | offline | unknown | busy


class JobOut(BaseModel):
    id: str
    printer_id: str
    copies: int
    state: str
    backend_job_id: str | None = None
    error: str | None = None
    template_id: str | None = None
    png_dir: str | None = None  # carpeta (dentro de png/) con las imágenes de este trabajo
