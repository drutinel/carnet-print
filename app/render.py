import io
import zlib

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


def images_to_pdf(images: list[Image.Image]) -> bytes:
    """PDF sin pérdida: una página por imagen, RGB 8 bits con FlateDecode, tamaño = px / 300 ppp.

    Pillow guarda RGB en PDF como JPEG (DCTDecode); aquí se escribe a mano para no perder
    calidad en los bordes del texto.
    """
    objects: list[bytes] = []  # objeto n = objects[n - 1]

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog, pages = add(b""), add(b"")
    kids = []
    for image in images:
        rgb = image.convert("RGB")
        w, h = rgb.size
        data = zlib.compress(rgb.tobytes(), 9)
        img = add(
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB"
            b" /BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n%s\nendstream"
            % (w, h, len(data), data)
        )
        pw, ph = w * 72 / DPI, h * 72 / DPI
        content = b"q %.4f 0 0 %.4f 0 0 cm /Im0 Do Q" % (pw, ph)
        stream = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content))
        kids.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.4f %.4f]"
            b" /Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>"
            % (pages, pw, ph, img, stream)
        ))
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages
    objects[pages - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids), len(kids))

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n%s\nendobj\n" % (n, body))
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
              % (len(objects) + 1, catalog, xref))
    return out.getvalue()


def faces_to_pdf(front: bytes, back: bytes) -> bytes:
    """PDF sin pérdida de 2 páginas (frente, reverso); el tamaño sale de píxeles / DPI."""
    return images_to_pdf([load_face(front), load_face(back)])


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
