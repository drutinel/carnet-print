import io
import json

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
def app(tmp_path):
    printers = tmp_path / "printers.yaml"
    printers.write_text("printers:\n  - {id: mock, label: Mock, adapter: mock}\n")
    return create_app(Settings(api_key="secret", printers_file=printers, data_dir=tmp_path))


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.put("/templates/acme", json={"org": "ACME"}, headers=KEY)
        yield c


def _put(client, client_id="acme-sa", **overrides):
    body = {"name": "ACME SA", "template_id": "acme", "editable": ["name", "ced"]} | overrides
    return client.put(f"/clients/{client_id}", json=body, headers=KEY)


def test_client_profile_persists_in_json_file(client, tmp_path):
    assert _put(client).json() == {
        "name": "ACME SA", "template_id": "acme", "editable": ["ced", "name"], "show_registry": False,
    }
    assert list(client.get("/clients", headers=KEY).json()) == ["acme-sa"]
    assert "acme-sa" in json.loads((tmp_path / "clients.json").read_text(encoding="utf-8"))["clients"]
    assert client.delete("/clients/acme-sa", headers=KEY).status_code == 204
    assert client.delete("/clients/acme-sa", headers=KEY).status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [{"name": " "}, {"template_id": "nope"}, {"editable": ["name", "template"]}, {"editable": "name"}],
)
def test_client_profile_is_validated(client, overrides):
    assert _put(client, **overrides).status_code == 422


def test_clients_require_api_key(client):
    assert client.get("/clients").status_code == 401
    assert client.put("/clients/x", json={}).status_code == 401


def test_kiosk_page_is_preconfigured_and_hides_key_from_other_machines(client):
    _put(client)
    res = client.get("/c/acme-sa")  # TestClient no es loopback
    assert res.status_code == 200 and "window.KIOSK=" in res.text
    kiosk = json.loads(res.text.split("window.KIOSK=")[1].split("</script>")[0])
    assert kiosk["template_id"] == "acme" and kiosk["editable"] == ["ced", "name"]
    assert kiosk["api_key"] == ""
    assert client.get("/c/nope").status_code == 404


def test_kiosk_page_gets_key_on_loopback(app):
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        c.put("/templates/acme", json={"org": "ACME"}, headers=KEY)
        _put(c)
        kiosk = json.loads(c.get("/c/acme-sa").text.split("window.KIOSK=")[1].split("</script>")[0])
    assert kiosk["api_key"] == "secret"


def test_job_pngs_are_saved_in_a_folder(client, tmp_path):
    files = {"front": ("f.png", _png(), "image/png"), "back": ("b.png", _png(), "image/png")}
    res = client.post(
        "/jobs", data={"printer_id": "mock", "control": "C-000007"}, files=files, headers=KEY
    )
    assert res.status_code == 202
    folder = tmp_path / "png" / res.json()["png_dir"]
    assert folder.name.endswith("_C-000007")
    assert {p.name for p in folder.iterdir()} == {"front.png", "back.png"}
    assert Image.open(folder / "front.png").size == (1011, 638)


def test_control_cannot_escape_the_png_folder(client, tmp_path):
    files = {"front": ("f.png", _png(), "image/png"), "back": ("b.png", _png(), "image/png")}
    res = client.post(
        "/jobs", data={"printer_id": "mock", "control": "../../evil"}, files=files, headers=KEY
    )
    assert res.status_code == 202
    assert (tmp_path / "png" / res.json()["png_dir"]).is_dir()
    assert not (tmp_path.parent / "evil").exists()


def _boot(res):
    return json.loads(res.text.split("window.BOOT=")[1].split("</script>")[0].split(";window.KIOSK=")[0])


def test_admin_page_gets_key_only_for_this_pc(app):
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as local:
        res = local.get("/ui/generador-carnets.html")
        assert _boot(res) == {"api_key": "secret"} and res.headers["cache-control"] == "no-store"
    with TestClient(app, client=("192.168.1.20", 50000)) as lan:  # otra máquina
        assert _boot(lan.get("/ui/generador-carnets.html")) == {"api_key": ""}


def test_key_is_not_given_when_host_header_is_not_local(app):
    # DNS rebinding: llega por loopback pero con el nombre de otro sitio
    with TestClient(app, base_url="http://evil.example", client=("127.0.0.1", 50000)) as c:
        assert _boot(c.get("/ui/generador-carnets.html")) == {"api_key": ""}


def test_favicon_does_not_404(app):
    with TestClient(app) as c:
        assert c.get("/favicon.ico").status_code == 204
