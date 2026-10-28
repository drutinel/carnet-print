import io
import json
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app

KEY = {"X-API-Key": "secret"}


def _png(size=(1011, 638), color=(255, 0, 0, 255)):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def client(tmp_path):
    printers = tmp_path / "printers.yaml"
    printers.write_text(
        "printers:\n"
        "  - {id: mock, label: Mock, adapter: mock,"
        " allowed_options: {RibbonName: [15Hologram, 0YMCKO], Free: []}}\n"
    )
    settings = Settings(
        api_key="secret", printers_file=printers, data_dir=tmp_path, max_upload_bytes=200_000
    )
    with TestClient(create_app(settings)) as c:
        yield c


def _post(client, **overrides):
    data = {"printer_id": "mock", "copies": "1", "options": "{}"} | overrides.pop("data", {})
    files = {
        "front": ("f.png", overrides.pop("front", _png()), "image/png"),
        "back": ("b.png", overrides.pop("back", _png(color=(0, 0, 255, 255))), "image/png"),
    }
    return client.post("/jobs", data=data, files=files, headers=overrides.pop("headers", KEY))


def _wait(client, job_id):
    for _ in range(100):
        job = client.get(f"/jobs/{job_id}", headers=KEY).json()
        if job["state"] != "queued":
            return job
        time.sleep(0.02)
    return job


def test_health_is_public(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_requires_api_key(client):
    for url in ("/printers", "/templates", "/cards"):
        assert client.get(url).status_code == 401
    assert _post(client, headers={}).status_code == 401


def test_lists_printers(client):
    res = client.get("/printers", headers=KEY)
    assert res.json() == [{"id": "mock", "label": "Mock", "status": "ready"}]


def test_job_is_submitted(client):
    options = json.dumps({"RibbonName": "15Hologram", "Free": "anything"})
    res = _post(client, data={"copies": "2", "options": options})
    assert res.status_code == 202
    job = _wait(client, res.json()["id"])
    assert job["state"] == "submitted"
    assert job["backend_job_id"] == "mock-1"


@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"data": {"printer_id": "nope"}}, 404),
        ({"front": b"not a png"}, 422),
        ({"front": _png((10, 10))}, 422),
        ({"front": _png() + b"x" * 300_000}, 413),
        ({"data": {"options": "{bad"}}, 422),
        ({"data": {"options": json.dumps({"Evil": "1"})}}, 422),
        ({"data": {"options": json.dumps({"RibbonName": "BAD"})}}, 422),
        ({"data": {"copies": "99"}}, 422),
        ({"data": {"template_id": "no-existe"}}, 422),
    ],
)
def test_rejects_invalid_input(client, kwargs, status):
    assert _post(client, **kwargs).status_code == status


def test_pdf_is_no_longer_accepted(client):
    res = client.post(
        "/jobs", data={"printer_id": "mock"},
        files={"pdf": ("c.pdf", b"%PDF-1.4\n", "application/pdf")}, headers=KEY,
    )
    assert res.status_code == 422


def test_requires_both_faces(client):
    res = client.post("/jobs", data={"printer_id": "mock"}, headers=KEY)
    assert res.status_code == 422


def test_exposes_printer_options(client):
    res = client.get("/printers/mock/options", headers=KEY)
    assert res.json()["RibbonName"] == ["15Hologram", "0YMCKO"]
    assert client.get("/printers/nope/options", headers=KEY).status_code == 404


def test_unknown_job_404(client):
    assert client.get("/jobs/nope", headers=KEY).status_code == 404


# --- plantillas: JSON junto al .exe, una activa para el API ---

def test_templates_persist_in_json_file(client, tmp_path):
    assert client.get("/templates", headers=KEY).json() == {"active": None, "templates": {}}
    client.put("/templates/gag", json={"org": "GAG", "band": "#1e40af"}, headers=KEY)
    client.put("/templates/otro", json={"org": "Otro"}, headers=KEY)
    listed = client.get("/templates", headers=KEY).json()
    assert listed["active"] == "gag"  # la primera queda activa
    assert set(listed["templates"]) == {"gag", "otro"}
    on_disk = json.loads((tmp_path / "templates.json").read_text(encoding="utf-8"))
    assert on_disk["templates"]["otro"] == {"org": "Otro"}


def test_activate_and_delete_template(client):
    client.put("/templates/a", json={"org": "A"}, headers=KEY)
    client.put("/templates/b", json={"org": "B"}, headers=KEY)
    assert client.post("/templates/b/activate", headers=KEY).json()["active"] == "b"
    assert client.post("/templates/zzz/activate", headers=KEY).status_code == 404
    assert client.delete("/templates/b", headers=KEY).status_code == 204
    assert client.get("/templates", headers=KEY).json()["active"] == "a"
    assert client.delete("/templates/b", headers=KEY).status_code == 404
    assert client.get("/templates/b", headers=KEY).status_code == 404


def test_template_id_must_be_safe(client):
    assert client.put("/templates/..%2Fx", json={}, headers=KEY).status_code in (404, 422)
    assert client.put("/templates/" + "a" * 65, json={}, headers=KEY).status_code == 422


def test_job_uses_active_template_unless_one_is_chosen(client):
    client.put("/templates/a", json={"org": "A"}, headers=KEY)
    client.put("/templates/b", json={"org": "B"}, headers=KEY)
    assert _post(client).json()["template_id"] == "a"
    assert _post(client, data={"template_id": "b"}).json()["template_id"] == "b"
    client.post("/templates/b/activate", headers=KEY)
    assert _post(client).json()["template_id"] == "b"


# --- carnets generados ---

def test_cards_persist_in_json_file(client, tmp_path):
    card = {"control": "C-000001", "data": {"name": "Ana"}, "prints": 1}
    assert client.put("/cards/C-000001", json=card, headers=KEY).status_code == 200
    client.put("/cards/C-000001", json=card | {"prints": 2}, headers=KEY)  # reimpresión
    assert client.get("/cards", headers=KEY).json() == [card | {"prints": 2}]
    on_disk = json.loads((tmp_path / "carnets.json").read_text(encoding="utf-8"))
    assert list(on_disk["cards"]) == ["C-000001"]


def test_corrupt_json_is_reported_not_overwritten(client, tmp_path):
    (tmp_path / "carnets.json").write_text("{roto", encoding="utf-8")
    assert client.get("/cards", headers=KEY).status_code == 422
    assert client.put("/cards/C-1", json={}, headers=KEY).status_code == 422
    assert (tmp_path / "carnets.json").read_text(encoding="utf-8") == "{roto"
