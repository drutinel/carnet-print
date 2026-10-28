import io

from PIL import Image, UnidentifiedImageError

DPI = 300
MIN_PX, MAX_PX = 400, 2400  # CR80 a 300 ppp: DS3 1015 x 640, ZC300 1006 x 640
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
FACE_KEYS = ("front", "back", "front_k", "back_k")


class ImageError(ValueError):
    """Imagen de carnet inválida."""


def load_face(data: bytes) -> Image.Image:
    """PNG de una cara -> RGB aplanado sobre blanco."""
    if not data.startswith(PNG_MAGIC):
        raise ImageError("Las caras del carnet deben ser PNG")
    try:
        image = Image.open(io.BytesIO(data))
        width, height = image.size
        if not (MIN_PX <= width <= MAX_PX and MIN_PX <= height <= MAX_PX):
            raise ImageError(f"Tamaño de imagen fuera de rango: {width}x{height}")
        rgba = image.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ImageError("PNG inválido") from exc
    flat = Image.new("RGB", rgba.size, "white")
    flat.paste(rgba, mask=rgba.getchannel("A"))
    return flat


def load_k_layer(data: bytes, size: tuple[int, int], name: str) -> Image.Image:
    """Capa negra (panel K): PNG del mismo tamaño que su cara -> 1 bit (negro < 128)."""
    layer = load_face(data)
    if layer.size != size:
        raise ImageError(
            f"La capa {name} mide {layer.size[0]}x{layer.size[1]} y su cara {size[0]}x{size[1]}"
        )
    return layer.convert("L").point(lambda v: 255 if v >= 128 else 0, mode="1")


def png_bytes(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG", dpi=(DPI, DPI))
    return out.getvalue()


def normalize_faces(raw: dict[str, bytes]) -> dict[str, bytes]:
    """Valida las caras recibidas y las devuelve como PNG listos para el puente.

    Color: RGB aplanado (sin alfa). Capas K: 1 bit, mismo tamaño que su cara.
    """
    faces = {k: load_face(raw[k]) for k in ("front", "back") if k in raw}
    out = {k: png_bytes(img) for k, img in faces.items()}
    for side in ("front", "back"):
        k = f"{side}_k"
        if k in raw:
            if side not in faces:
                raise ImageError(f"Llegó {k} sin {side}")
            out[k] = png_bytes(load_k_layer(raw[k], faces[side].size, k))
    return out
