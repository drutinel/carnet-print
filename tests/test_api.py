import json
import time

import pytest
from fastapi.testclient import TestClient

from conftest import KEY, card_body, data_uri, png_bytes


def _post(client, **overrides):
    data = {"printer_id": "mock", "copies": "1", "options": "{}"} | overrides.pop("data", {})
    files = {
        "front": ("f.png", overrides.pop("front", png_bytes()), "image/png"),
        "back": ("b.png", overrides.pop("back", png_bytes(color=(0, 0, 255, 255))), "image/png"),
    }
    return client.post("/jobs", data=data, files=files, headers=overrides.pop("headers", KEY))


def _wait(client, job_id):
    for _ in range(100):
        job = client.get(f"/jobs/{job_id}", headers=KEY).json()
        if job["state"] != "queued":
            return job
        time.sleep(0.02)
    return job


def test_health_is_public_and_reports_version(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["version"]


def test_requires_api_key(client):
    for url in ("/printers", "/templates", "/cards", "/settings", "/clients"):
        assert client.get(url).status_code == 401
    assert client.get("/printers", headers={"X-API-Key": "otra"}).status_code == 401
    assert _post(client, headers={}).status_code == 401


def test_lists_printers(client):
    assert client.get("/printers", headers=KEY).json() == [{"id": "mock", "label": "Mock", "status": "ready"}]


def test_job_is_submitted(client):
    options = json.dumps({"RibbonName": "15Hologram", "Free": "anything"})
    res = _post(client, data={"copies": "2", "options": options})
    assert res.status_code == 202
    job = _wait(client, res.json()["id"])
    assert job["state"] == "submitted" and job["backend_job_id"] == "mock-1"


@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"data": {"printer_id": "nope"}}, 404),
        ({"front": b"not a png"}, 422),
        ({"front": png_bytes((10, 10))}, 422),
        ({"front": png_bytes() + b"x" * 300_000}, 413),
        ({"data": {"options": "{bad"}}, 422),
        ({"data": {"options": json.dumps({"Evil": "1"})}}, 422),
        ({"data": {"options": json.dumps({"RibbonName": "BAD"})}}, 422),
        ({"data": {"copies": "99"}}, 422),
        ({"data": {"template_id": "no-existe"}}, 422),
    ],
)
def test_rejects_invalid_input(client, kwargs, status):
    assert _post(client, **kwargs).status_code == status


def test_pdf_is_not_accepted(client):
    res = client.post("/jobs", data={"printer_id": "mock"},
                      files={"pdf": ("c.pdf", b"%PDF-1.4\n", "application/pdf")}, headers=KEY)
    assert res.status_code == 422


def test_unknown_job_404(client):
    assert client.get("/jobs/nope", headers=KEY).status_code == 404


def test_exposes_printer_options(client):
    assert client.get("/printers/mock/options", headers=KEY).json()["RibbonName"] == ["15Hologram", "0YMCKO"]
    assert client.get("/printers/nope/options", headers=KEY).status_code == 404


def test_old_jobs_are_forgotten(make_app, monkeypatch):
    import app.jobs as jobs_module
    monkeypatch.setattr(jobs_module, "MAX_JOBS", 3)
    with TestClient(make_app()) as c:
        ids = []
        for _ in range(6):
            ids.append(_post(c).json()["id"])
            _wait(c, ids[-1])
        assert c.get(f"/jobs/{ids[0]}", headers=KEY).status_code == 404
        assert c.get(f"/jobs/{ids[-1]}", headers=KEY).status_code == 200


# --- plantillas ---

def test_templates_persist_in_json_file(client, tmp_path):
    assert client.get("/templates", headers=KEY).json() == {"active": None, "templates": {}}
    client.put("/templates/gag", json={"name": "GAG", "org": "GAG", "band": "#1e40af"}, headers=KEY)
    client.put("/templates/otro", json={"org": "Otro"}, headers=KEY)
    listed = client.get("/templates", headers=KEY).json()
    assert listed["active"] == "gag" and set(listed["templates"]) == {"gag", "otro"}
    on_disk = json.loads((tmp_path / "templates.json").read_text(encoding="utf-8"))
    assert on_disk["templates"]["otro"]["org"] == "Otro"


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


# --- entradas validadas y acotadas ---

@pytest.mark.parametrize(
    "url,body",
    [
        ("/templates/x", {"org": "x" * 201}),                      # texto demasiado largo
        ("/templates/x", {"nope": "campo desconocido"}),
        ("/templates/x", {"img": {"logo1": "javascript:alert(1)"}}),  # no es un data URI de imagen
        ("/templates/x", {"img": {"logo1": "data:image/svg+xml;base64,AAAA"}}),
        ("/settings", {"quality": "ultra"}),
        ("/settings", {"cal": {"p": {"ox": 999}}}),
        ("/settings", {"hopper": "99"}),
    ],
)
def test_json_bodies_are_validated(client, url, body):
    assert client.put(url, json=body, headers=KEY).status_code == 422


def test_huge_image_is_rejected(client):
    huge = "data:image/png;base64," + "A" * 3_000_001
    assert client.put("/templates/x", json={"img": {"logo1": huge}}, headers=KEY).status_code == 422


def test_settings_persist_in_json_file(client, tmp_path):
    assert client.get("/settings", headers=KEY).json() == {}
    cfg = {"printer": "p", "quality": "fine", "hopper": "2", "cal": {"p": {"rotate": True, "split": False, "ox": 0.4, "oy": -0.2}}}
    assert client.put("/settings", json=cfg, headers=KEY).json() == cfg
    assert client.put("/settings", json={"printer": "carta"}, headers=KEY).status_code == 200
    assert client.get("/settings", headers=KEY).json()["printer"] == "carta"  # reemplaza, no mezcla
    assert json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["printer"] == "carta"


def test_old_calibration_keys_are_ignored(client):
    cfg = {"cal": {"p": {"bleed": True, "ox": 1}}}  # `bleed` ya no existe
    assert client.put("/settings", json=cfg, headers=KEY).json()["cal"]["p"] == {"rotate": False, "split": False, "ox": 1.0, "oy": 0.0}


# --- carnets: el servidor asigna el control ---

def test_server_assigns_control_and_code(client):
    a = client.post("/cards", json=card_body("Ana"), headers=KEY)
    b = client.post("/cards", json=card_body("Beto"), headers=KEY)
    assert a.status_code == b.status_code == 201
    assert (a.json()["control"], b.json()["control"]) == ("C-000001", "C-000002")
    assert a.json()["data"]["code"] == "GAG-000001"   # código automático con el prefijo de la plantilla
    assert a.json()["prints"] == 1 and a.json()["voided"] is False


def test_given_code_is_kept_and_client_cannot_choose_the_control(client):
    body = card_body("Ana", control="C-999999", prints=50)
    assert client.post("/cards", json=body, headers=KEY).status_code == 422  # campos que no se aceptan
    ok = client.post("/cards", json=card_body("Ana") | {"data": {"name": "Ana", "code": "MIO-1"}}, headers=KEY)
    assert ok.json()["data"]["code"] == "MIO-1" and ok.json()["control"] == "C-000001"


def test_concurrent_creates_never_share_a_control(client):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda i: client.post("/cards", json=card_body(f"P{i}"), headers=KEY), range(24)))
    controls = [r.json()["control"] for r in results]
    assert len(set(controls)) == 24 == len(client.get("/cards", headers=KEY).json())


def test_registry_is_light_and_full_card_has_images(client, tmp_path):
    uri = data_uri()
    created = client.post("/cards", json=card_body(img={"photo": uri, "logo1": uri}), headers=KEY).json()
    assert "img" not in created
    listed = client.get("/cards", headers=KEY).json()
    assert "img" not in listed[0]
    assert client.get("/cards/" + created["control"], headers=KEY).json()["img"]["photo"] == uri
    assert client.get("/cards?full=true", headers=KEY).json()[0]["img"]["logo1"] == uri
    # las imágenes no viven dentro del JSON y la misma imagen se guarda una sola vez
    assert "base64" not in (tmp_path / "carnets.json").read_text(encoding="utf-8")
    assert len(list((tmp_path / "images").iterdir())) == 1


def test_reprint_void_and_restore(client):
    control = client.post("/cards", json=card_body(), headers=KEY).json()["control"]
    assert client.post(f"/cards/{control}/reprint", headers=KEY).json()["prints"] == 2
    assert client.post(f"/cards/{control}/void", headers=KEY).json()["voided"] is True
    assert client.post("/cards/C-404/reprint", headers=KEY).status_code == 404
    backup = client.get("/cards?full=true", headers=KEY).json()[0]
    assert client.put("/cards/C-000777", json=backup, headers=KEY).json()["control"] == "C-000777"


def test_corrupt_json_is_reported_not_overwritten(client, tmp_path):
    (tmp_path / "carnets.json").write_text("{roto", encoding="utf-8")
    assert client.get("/cards", headers=KEY).status_code == 422
    assert client.post("/cards", json=card_body(), headers=KEY).status_code == 422
    assert (tmp_path / "carnets.json").read_text(encoding="utf-8") == "{roto"


def test_old_json_with_inline_images_is_compacted_on_start(make_app, tmp_path):
    uri = data_uri()
    (tmp_path / "carnets.json").write_text(json.dumps(
        {"cards": {"C-000001": {"control": "C-000001", "tpl": {}, "data": {"name": "Viejo"}, "img": {"photo": uri}}}}))
    with TestClient(make_app()) as c:
        assert "base64" not in (tmp_path / "carnets.json").read_text()
        assert c.get("/cards/C-000001", headers=KEY).json()["img"]["photo"] == uri
