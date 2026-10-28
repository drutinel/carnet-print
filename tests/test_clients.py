import json

import pytest
from fastapi.testclient import TestClient

from conftest import KEY, card_body, png_bytes


@pytest.fixture
def admin(make_app):
    with TestClient(make_app()) as c:
        c.put("/templates/acme", json={"org": "ACME", "prefix": "AC-"}, headers=KEY)
        c.put("/templates/otra", json={"org": "OTRA"}, headers=KEY)
        yield c


def _put(admin, client_id="acme-sa", **overrides):
    body = {"name": "ACME SA", "template_id": "acme", "editable": ["name", "ced"]} | overrides
    return admin.put(f"/clients/{client_id}", json=body, headers=KEY)


def _kiosk_token(admin, client_id="acme-sa") -> dict:
    page = admin.get(f"/c/{client_id}").text
    kiosk = json.loads(page.split("window.KIOSK=")[1].split("</script>")[0])
    return {"X-API-Key": kiosk["api_key"]}


def test_client_profile_persists_and_never_lists_its_token(admin, tmp_path):
    assert _put(admin).json() == {
        "name": "ACME SA", "template_id": "acme", "editable": ["ced", "name"], "show_registry": False,
    }
    assert "token" not in admin.get("/clients", headers=KEY).json()["acme-sa"]
    stored = json.loads((tmp_path / "clients.json").read_text(encoding="utf-8"))["clients"]["acme-sa"]
    assert len(stored["token"]) >= 24
    assert admin.delete("/clients/acme-sa", headers=KEY).status_code == 204
    assert admin.delete("/clients/acme-sa", headers=KEY).status_code == 404


def test_updating_a_profile_keeps_its_token(admin):
    _put(admin)
    token = _kiosk_token(admin)
    _put(admin, name="ACME SA (nuevo nombre)")
    assert _kiosk_token(admin) == token


@pytest.mark.parametrize(
    "overrides",
    [{"name": " "}, {"template_id": "nope"}, {"editable": ["name", "template"]}, {"editable": "name"}],
)
def test_client_profile_is_validated(admin, overrides):
    assert _put(admin, **overrides).status_code == 422


def test_clients_are_admin_only(admin):
    _put(admin)
    kiosk = _kiosk_token(admin)
    assert admin.get("/clients").status_code == 401
    assert admin.get("/clients", headers=kiosk).status_code == 403
    assert admin.put("/clients/x", json={}, headers=kiosk).status_code == 403


def test_kiosk_page_carries_its_own_token_not_the_api_key(admin):
    _put(admin)
    page = admin.get("/c/acme-sa").text
    kiosk = json.loads(page.split("window.KIOSK=")[1].split("</script>")[0])
    assert kiosk["template_id"] == "acme" and kiosk["editable"] == ["ced", "name"]
    assert kiosk["api_key"] != "secret" and "secret" not in page
    assert admin.get("/c/nope").status_code == 404


def test_kiosk_token_is_enforced_by_the_server(admin):
    _put(admin)
    kiosk = _kiosk_token(admin)
    # lo que sí puede
    assert admin.get("/printers", headers=kiosk).status_code == 200
    assert admin.get("/settings", headers=kiosk).status_code == 200
    assert list(admin.get("/templates", headers=kiosk).json()["templates"]) == ["acme"]  # solo la suya
    # lo que no
    assert admin.get("/templates/otra", headers=kiosk).status_code == 403
    assert admin.put("/templates/acme", json={"org": "hack"}, headers=kiosk).status_code == 403
    assert admin.post("/templates/otra/activate", headers=kiosk).status_code == 403
    assert admin.delete("/templates/acme", headers=kiosk).status_code == 403
    assert admin.put("/settings", json={"printer": "x"}, headers=kiosk).status_code == 403
    assert admin.get("/cards", headers=kiosk).status_code == 403            # perfil sin registro
    assert admin.post("/cards/C-000001/void", headers=kiosk).status_code == 403


def test_kiosk_always_prints_and_registers_with_its_own_template(admin):
    _put(admin)
    kiosk = _kiosk_token(admin)
    files = {"front": ("f.png", png_bytes(), "image/png"), "back": ("b.png", png_bytes(), "image/png")}
    other = admin.post("/jobs", data={"printer_id": "mock", "template_id": "otra"}, files=files, headers=kiosk)
    assert other.status_code == 403
    own = admin.post("/jobs", data={"printer_id": "mock"}, files=files, headers=kiosk)
    assert own.status_code == 202 and own.json()["template_id"] == "acme"
    card = admin.post("/cards", json=card_body() | {"templateId": "otra"}, headers=kiosk).json()
    assert card["templateId"] == "acme"
    assert admin.get(f"/cards/{card['control']}", headers=KEY).json()["templateId"] == "acme"


def test_kiosk_with_registry_can_read_and_reprint_but_not_void_or_export(admin):
    _put(admin, show_registry=True)
    kiosk = _kiosk_token(admin)
    control = admin.post("/cards", json=card_body(), headers=kiosk).json()["control"]
    assert len(admin.get("/cards", headers=kiosk).json()) == 1
    assert admin.post(f"/cards/{control}/reprint", headers=kiosk).json()["prints"] == 2
    assert admin.get("/cards?full=true", headers=kiosk).status_code == 403
    assert admin.post(f"/cards/{control}/void", headers=kiosk).status_code == 403
    assert admin.put(f"/cards/{control}", json=card_body(), headers=kiosk).status_code == 403


def test_deleting_a_profile_revokes_its_token(admin):
    _put(admin)
    kiosk = _kiosk_token(admin)
    admin.delete("/clients/acme-sa", headers=KEY)
    assert admin.get("/printers", headers=kiosk).status_code == 401


def test_admin_page_gets_key_only_for_this_pc(make_app):
    def boot(res):
        return json.loads(res.text.split("window.BOOT=")[1].split("</script>")[0])
    with TestClient(make_app(), base_url="http://localhost", client=("127.0.0.1", 50000)) as local:
        res = local.get("/ui/generador-carnets.html")
        assert boot(res) == {"api_key": "secret"} and res.headers["cache-control"] == "no-store"
    with TestClient(make_app(), client=("192.168.1.20", 50000)) as lan:   # otra máquina
        assert boot(lan.get("/ui/generador-carnets.html")) == {"api_key": ""}
    # DNS rebinding: llega por loopback pero con el nombre de otro sitio
    with TestClient(make_app(), base_url="http://evil.example", client=("127.0.0.1", 50000)) as evil:
        assert boot(evil.get("/ui/generador-carnets.html")) == {"api_key": ""}


def test_favicon_does_not_404(client):
    assert client.get("/favicon.ico").status_code == 204


def test_each_kiosk_has_its_own_draft_and_last_card(admin):
    _put(admin)
    _put(admin, "otro", name="Otro SA", template_id="otra")
    one, two = _kiosk_token(admin), _kiosk_token(admin, "otro")
    admin.put("/draft", json={"name": "Del admin"}, headers=KEY)
    admin.put("/draft", json={"name": "Del uno"}, headers=one)
    assert admin.get("/draft", headers=one).json()["name"] == "Del uno"
    assert admin.get("/draft", headers=two).json() == {}                    # no se mezclan
    assert admin.get("/draft", headers=KEY).json()["name"] == "Del admin"
    admin.post("/cards", json=card_body("De uno"), headers=one)
    admin.post("/cards", json=card_body("De otro"), headers=two)
    assert admin.get("/cards/last", headers=one).json()["data"]["name"] == "De uno"   # sin registro, pero el suyo
    assert admin.get("/cards/last", headers=two).json()["data"]["name"] == "De otro"
    assert admin.get("/cards/last", headers=KEY).json()["data"]["name"] == "De otro"  # el admin ve el último de todos
