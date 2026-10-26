import io
import re
import time
import zlib

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.printers import bridge, mock
from app.printers.base import PrintRequest
from app.printers.entrust_sdk import EntrustSdkAdapter
from app.render import images_to_pdf

KEY = {"X-API-Key": "secret"}
SIZE = (1015, 640)  # página nativa de la DS3 a 300 ppp


def _png(size=SIZE, color=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _pattern(size=SIZE):
    """Imagen con bordes duros (texto simulado) para detectar compresión con pérdida."""
    img = Image.new("RGB", size, (30, 60, 160))
    px = img.load()
    for x in range(0, size[0], 3):
        for y in range(100, 140):
            px[x, y] = (255, 255, 255)
    return img


@pytest.fixture
def captured(monkeypatch):
    """El mock acepta PNG por cara y guarda copia de lo que recibe (los temporales se borran)."""
    seen = []

    def submit(self, request: PrintRequest) -> str:
        seen.append({
            "pdf": request.pdf_path.read_bytes() if request.pdf_path else None,
            "faces": {k: p.read_bytes() for k, p in (request.faces or {}).items()},
        })
        return "mock-1"

    monkeypatch.setattr(mock.MockAdapter, "submit", submit)
    return seen


@pytest.fixture
def client(tmp_path):
    printers = tmp_path / "printers.yaml"
    printers.write_text("printers:\n  - {id: mock, label: Mock, adapter: mock}\n")
    settings = Settings(api_key="secret", printers_file=printers, max_pdf_bytes=2_000_000)
    with TestClient(create_app(settings)) as c:
        yield c


def _post(client, **faces):
    files = {k: (f"{k}.png", v, "image/png") for k, v in faces.items()}
    return client.post("/jobs", data={"printer_id": "mock"}, files=files, headers=KEY)


def _wait(client, job_id):
    for _ in range(100):
        job = client.get(f"/jobs/{job_id}", headers=KEY).json()
        if job["state"] != "queued":
            return job
        time.sleep(0.02)
    return job


def test_png_faces_reach_sdk_adapter_without_pdf(monkeypatch, client, captured):
    monkeypatch.setattr(mock.MockAdapter, "accepts_faces", True)
    k = _png(color=(255, 255, 255))
    res = _post(client, front=_png(), back=_png(color=(0, 0, 255)), front_k=k)
    assert res.status_code == 202
    assert _wait(client, res.json()["id"])["state"] == "submitted"
    got = captured[0]
    assert got["pdf"] is None
    assert set(got["faces"]) == {"front", "back", "front_k"}
    front = Image.open(io.BytesIO(got["faces"]["front"]))
    assert front.size == SIZE and front.mode == "RGB"
    assert Image.open(io.BytesIO(got["faces"]["front_k"])).mode == "1"


def test_k_layer_size_must_match_face(monkeypatch, client, captured):
    monkeypatch.setattr(mock.MockAdapter, "accepts_faces", True)
    res = _post(client, front=_png(), back=_png(), back_k=_png((1011, 638)))
    assert res.status_code == 422
    assert "back_k" in res.json()["detail"]


def test_pdf_adapter_gets_lossless_pdf(client, captured):
    res = _post(client, front=_png(), back=_png(color=(0, 0, 255)))
    assert res.status_code == 202
    _wait(client, res.json()["id"])
    pdf = captured[0]["pdf"]
    assert pdf.startswith(b"%PDF-") and b"DCTDecode" not in pdf and b"FlateDecode" in pdf
    assert captured[0]["faces"] == {}


def test_lossless_pdf_roundtrip_is_pixel_exact():
    pdfium = pytest.importorskip("pypdfium2")
    src = [_pattern(), _pattern((1006, 640))]
    pdf = images_to_pdf(src)
    # Los píxeles guardados en el PDF son exactamente los originales (Flate, sin JPEG)
    streams = re.findall(rb"/FlateDecode /Length (\d+) >>\nstream\n", pdf)
    starts = [m.end() for m in re.finditer(rb"/FlateDecode /Length \d+ >>\nstream\n", pdf)]
    assert len(starts) == 2
    for start, length, original in zip(starts, streams, src):
        raw = zlib.decompress(pdf[start:start + int(length)])
        assert raw == original.tobytes()
    # Y es un PDF válido con el tamaño físico correcto (px / 300 ppp)
    doc = pdfium.PdfDocument(pdf)
    assert len(doc) == 2
    for page, original in zip(doc, src):
        assert page.get_size() == pytest.approx((original.width * 72 / 300, original.height * 72 / 300))
    doc.close()


def test_bridge_passes_png_paths(monkeypatch, tmp_path):
    exe = tmp_path / "CardBridge.exe"
    exe.write_text("")
    calls = []
    monkeypatch.setattr(
        bridge.subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or bridge.subprocess.CompletedProcess(
            cmd, 0, '{"ok": true, "printerJobId": 9}\n', ""),
    )
    faces = {k: tmp_path / f"{k}.png" for k in ("front", "back", "back_k")}
    job = EntrustSdkAdapter("XPS Card Printer", str(exe)).submit(
        PrintRequest(pdf_path=None, copies=1, options={}, faces=faces))
    assert job.endswith("9")
    cmd = calls[0]
    assert cmd[cmd.index("--front") + 1] == str(faces["front"])
    assert cmd[cmd.index("--back-k") + 1] == str(faces["back_k"])
    assert "--front-k" not in cmd
