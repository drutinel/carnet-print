import io
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.printers import bridge, mock
from app.printers.base import PrintRequest
from app.printers.entrust_sdk import EntrustSdkAdapter
from conftest import KEY, png_bytes

SIZE = (1015, 640)  # página nativa de la DS3 a 300 ppp


@pytest.fixture
def captured(monkeypatch):
    """El mock guarda copia de lo que recibe (los temporales se borran al terminar el trabajo)."""
    seen = []

    def submit(self, request: PrintRequest) -> str:
        seen.append({k: p.read_bytes() for k, p in request.faces.items()})
        return "mock-1"

    monkeypatch.setattr(mock.MockAdapter, "submit", submit)
    return seen


@pytest.fixture
def client(tmp_path):
    printers = tmp_path / "printers.yaml"
    printers.write_text("printers:\n  - {id: mock, label: Mock, adapter: mock}\n")
    settings = Settings(api_key="secret", printers_file=printers, max_upload_bytes=2_000_000, data_dir=tmp_path)
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


def test_png_faces_reach_the_adapter_untouched_by_pdf(client, captured):
    k = png_bytes(SIZE, (255, 255, 255, 255))
    res = _post(client, front=png_bytes(SIZE), back=png_bytes(SIZE, (0, 0, 255, 255)), front_k=k)
    assert res.status_code == 202
    assert _wait(client, res.json()["id"])["state"] == "submitted"
    got = captured[0]
    assert set(got) == {"front", "back", "front_k"}
    front = Image.open(io.BytesIO(got["front"]))
    assert front.size == SIZE and front.mode == "RGB"
    assert Image.open(io.BytesIO(got["front_k"])).mode == "1"


def test_k_layer_size_must_match_face(client, captured):
    res = _post(client, front=png_bytes(SIZE), back=png_bytes(SIZE), back_k=png_bytes((1011, 638)))
    assert res.status_code == 422
    assert "back_k" in res.json()["detail"]


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
    job = EntrustSdkAdapter("XPS Card Printer", str(exe)).submit(PrintRequest(copies=1, options={}, faces=faces))
    assert job.endswith("9")
    cmd = calls[0]
    assert cmd[cmd.index("--front") + 1] == str(faces["front"])
    assert cmd[cmd.index("--back-k") + 1] == str(faces["back_k"])


def test_bridge_needs_both_faces(tmp_path):
    exe = tmp_path / "CardBridge.exe"
    exe.write_text("")
    from app.printers.base import PrintError
    with pytest.raises(PrintError, match="front/back"):
        EntrustSdkAdapter("P", str(exe)).submit(PrintRequest(copies=1, options={}, faces={"front": tmp_path / "f.png"}))
