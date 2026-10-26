import io
import json
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app

KEY = {"X-API-Key": "secret"}
PDF = b"%PDF-1.4\n%fake\n"


@pytest.fixture
def client(tmp_path):
    printers = tmp_path / "printers.yaml"
    printers.write_text(
        "printers:\n"
        "  - {id: mock, label: Mock, adapter: mock,"
        " allowed_options: {RibbonName: [15Hologram, 0YMCKO], Free: []}}\n"
    )
    settings = Settings(api_key="secret", printers_file=printers, max_pdf_bytes=200_000)
    with TestClient(create_app(settings)) as c:
        yield c


def _post(client, **overrides):
    data = {"printer_id": "mock", "copies": "1", "options": "{}"} | overrides.pop("data", {})
    files = {"pdf": ("c.pdf", overrides.pop("pdf", PDF), "application/pdf")}
    return client.post("/jobs", data=data, files=files, headers=overrides.pop("headers", KEY))


def test_health_is_public(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_requires_api_key(client):
    assert client.get("/printers").status_code == 401
    assert _post(client, headers={}).status_code == 401


def test_lists_printers(client):
    res = client.get("/printers", headers=KEY)
    assert res.json() == [{"id": "mock", "label": "Mock", "status": "ready"}]


def test_job_is_submitted(client):
    options = json.dumps({"RibbonName": "15Hologram", "Free": "anything"})
    res = _post(client, data={"copies": "2", "options": options})
    assert res.status_code == 202
    job_id = res.json()["id"]
    for _ in range(50):
        job = client.get(f"/jobs/{job_id}", headers=KEY).json()
        if job["state"] != "queued":
            break
        time.sleep(0.02)
    assert job["state"] == "submitted"
    assert job["backend_job_id"] == "mock-1"


@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"data": {"printer_id": "nope"}}, 404),
        ({"pdf": b"not a pdf"}, 422),
        ({"pdf": PDF + b"x" * 300_000}, 413),
        ({"data": {"options": "{bad"}}, 422),
        ({"data": {"options": json.dumps({"Evil": "1"})}}, 422),
        ({"data": {"options": json.dumps({"RibbonName": "BAD"})}}, 422),
        ({"data": {"copies": "99"}}, 422),
    ],
)
def test_rejects_invalid_input(client, kwargs, status):
    assert _post(client, **kwargs).status_code == status


def test_exposes_printer_options(client):
    res = client.get("/printers/mock/options", headers=KEY)
    assert res.json()["RibbonName"] == ["15Hologram", "0YMCKO"]
    assert client.get("/printers/nope/options", headers=KEY).status_code == 404


def test_unknown_job_404(client):
    assert client.get("/jobs/nope", headers=KEY).status_code == 404


def _png(size=(1011, 638), color=(255, 0, 0, 255)):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _post_faces(client, front, back, headers=KEY):
    files = {"front": ("f.png", front, "image/png"), "back": ("b.png", back, "image/png")}
    return client.post("/jobs", data={"printer_id": "mock"}, files=files, headers=headers)


def test_faces_are_converted_to_two_page_pdf(client):
    res = _post_faces(client, _png(), _png(color=(0, 0, 255, 255)))
    assert res.status_code == 202


def test_faces_reject_bad_images(client):
    assert _post_faces(client, b"nope", _png()).status_code == 422
    assert _post_faces(client, _png((10, 10)), _png()).status_code == 422


def test_requires_pdf_or_faces(client):
    res = client.post("/jobs", data={"printer_id": "mock"}, headers=KEY)
    assert res.status_code == 422
