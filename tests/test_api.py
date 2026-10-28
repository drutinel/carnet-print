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
    assert a.json()["data"]["code"] == "GAG-00001"   # código automático con el prefijo de la plantilla
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


def test_clients_without_token_get_one_on_start(make_app, tmp_path):
    (tmp_path / "clients.json").write_text(json.dumps({"clients": {"viejo": {
        "name": "Viejo", "template_id": "a", "editable": ["name"], "show_registry": False}}}))
    with TestClient(make_app()) as c:
        stored = json.loads((tmp_path / "clients.json").read_text())["clients"]["viejo"]
        assert len(stored["token"]) >= 24
        assert c.get("/c/viejo").status_code == 200


# --- layout editable de la tarjeta ---

LAYOUT = {
    "front": {
        "margins": {"top": 6, "right": 8, "bottom": 6, "left": 8},
        "gap": 8,
        "photo": {"width": 80, "height": 100},
        "fields": {"cat": {"label": "Rango", "fit": "shrink"}, "extra": {"label": "Cargo", "fit": "wrap", "maxLines": 2}},
        "footer": {"code": {"label": "Código"}},
    },
    "back": {"margins": {"top": 10}},
}


def test_template_layout_roundtrips_and_is_optional(client):
    client.put("/templates/a", json={"org": "A"}, headers=KEY)
    assert client.get("/templates/a", headers=KEY).json()["layout"] is None   # sin layout = valores por defecto
    client.put("/templates/a", json={"org": "A", "layout": LAYOUT}, headers=KEY)
    assert client.get("/templates/a", headers=KEY).json()["layout"]["front"]["fields"]["cat"]["label"] == "Rango"


@pytest.mark.parametrize(
    "layout",
    [
        {"front": {"fields": {"nombre": {"label": "x"}}}},                 # campo que no existe
        {"front": {"fields": {"cat": {"fit": "explotar"}}}},
        {"front": {"fields": {"cat": {"size": 99}}}},
        {"front": {"fields": {"cat": {"label": "x" * 41}}}},
        {"front": {"margins": {"top": -1}}},
        {"front": {"photo": {"width": 500}}},
        {"front": {"colorsito": 1}},                                       # clave desconocida (erratas del JSON)
        {"back": {"margins": {"left": 41}}},
    ],
)
def test_layout_is_validated(client, layout):
    assert client.put("/templates/a", json={"layout": layout}, headers=KEY).status_code == 422


def test_card_keeps_the_layout_it_was_made_with(client):
    body = card_body()
    body["tpl"] = {**body["tpl"], "layout": LAYOUT}
    control = client.post("/cards", json=body, headers=KEY).json()["control"]
    assert client.get(f"/cards/{control}", headers=KEY).json()["tpl"]["layout"]["front"]["gap"] == 8


def test_data_dir_is_created_if_missing(make_app, tmp_path):
    with TestClient(make_app(data_dir=tmp_path / "nueva" / "carpeta")) as c:
        assert c.post("/cards", json=card_body(), headers=KEY).status_code == 201
        assert (tmp_path / "nueva" / "carpeta" / "carnets.json").exists()


# --- borrador del titular, «continuar desde el último» y un JSON por carnet ---

def test_draft_survives_restart_and_keeps_the_photo_out_of_the_json(make_app, tmp_path):
    uri = data_uri()
    draft = {"name": "Ana", "ced": "001-1234567-3", "cat": "GENERAL", "photo": uri}
    with TestClient(make_app()) as c:
        assert c.get("/draft", headers=KEY).json() == {}
        assert c.put("/draft", json=draft, headers=KEY).status_code == 200
    assert "base64" not in (tmp_path / "draft.json").read_text(encoding="utf-8")
    with TestClient(make_app()) as again:   # «reiniciar»
        got = again.get("/draft", headers=KEY).json()
        assert got["name"] == "Ana" and got["photo"] == uri
        assert again.delete("/draft", headers=KEY).status_code == 204
        assert again.get("/draft", headers=KEY).json() == {}


@pytest.mark.parametrize("body", [{"name": "x" * 201}, {"photo": "javascript:alert(1)"}, {"otro": "campo"}])
def test_draft_is_validated(client, body):
    assert client.put("/draft", json=body, headers=KEY).status_code == 422


def test_last_card_is_the_latest_one_with_its_images(client):
    assert client.get("/cards/last", headers=KEY).status_code == 404
    client.post("/cards", json=card_body("Ana"), headers=KEY)
    uri = data_uri()
    client.post("/cards", json=card_body("Beto", img={"photo": uri}), headers=KEY)
    last = client.get("/cards/last", headers=KEY).json()
    assert last["data"]["name"] == "Beto" and last["control"] == "C-000002" and last["img"]["photo"] == uri


def test_each_card_is_also_written_as_its_own_json_file(client, tmp_path):
    uri = data_uri()
    control = client.post("/cards", json=card_body("Ana", img={"photo": uri}), headers=KEY).json()["control"]
    file = tmp_path / "carnets" / f"{control}.json"
    assert json.loads(file.read_text(encoding="utf-8"))["data"]["name"] == "Ana"
    assert json.loads(file.read_text(encoding="utf-8"))["img"]["photo"] == uri   # autocontenido: lleva la foto
    client.post(f"/cards/{control}/reprint", headers=KEY)
    client.post(f"/cards/{control}/void", headers=KEY)
    saved = json.loads(file.read_text(encoding="utf-8"))
    assert saved["prints"] == 2 and saved["voided"] is True               # la copia sigue al carnet


def test_card_files_are_restorable_with_the_normal_import(client, tmp_path):
    control = client.post("/cards", json=card_body("Ana"), headers=KEY).json()["control"]
    card = json.loads((tmp_path / "carnets" / f"{control}.json").read_text(encoding="utf-8"))
    assert client.put("/cards/C-000050", json=card, headers=KEY).status_code == 200


def test_cards_from_before_get_their_file_on_start(make_app, tmp_path):
    (tmp_path / "carnets.json").write_text(json.dumps({"cards": {"C-000001": {
        "control": "C-000001", "tpl": {}, "data": {"name": "Viejo"}, "img": {}, "createdAt": 1, "prints": 1, "voided": False}}}))
    with TestClient(make_app()):
        assert json.loads((tmp_path / "carnets" / "C-000001.json").read_text())["data"]["name"] == "Viejo"


# --- editar un carnet ya emitido ---

def _issued(client, name="Ana", **extra):
    return client.post("/cards", json=card_body(name, **extra), headers=KEY).json()


def test_edit_keeps_control_code_and_history(client, tmp_path):
    issued = _issued(client, "Ana Perez")
    control, code = issued["control"], issued["data"]["code"]
    fixed = card_body("Ana Pérez")                                   # corrige el nombre; el código viene vacío
    res = client.patch(f"/cards/{control}", json=fixed, headers=KEY)
    assert res.status_code == 200
    card = client.get(f"/cards/{control}", headers=KEY).json()
    assert card["data"]["name"] == "Ana Pérez" and card["data"]["code"] == code     # el código no cambia
    assert card["control"] == control and card["createdAt"] == issued["createdAt"] and card["prints"] == 1
    assert card["updatedBy"] == "admin" and card["updatedAt"] >= card["createdAt"]
    assert [r["data"]["name"] for r in card["revisions"]] == ["Ana Perez"]          # lo anterior queda a la vista
    assert len(client.get("/cards", headers=KEY).json()) == 1                       # no creó otro carnet
    assert json.loads((tmp_path / "carnets" / f"{control}.json").read_text(encoding="utf-8"))["data"]["name"] == "Ana Pérez"


def test_edit_can_replace_images_and_explicit_code(client):
    uri = data_uri()
    control = _issued(client)["control"]
    body = card_body("Ana", img={"photo": uri}) | {"data": {"name": "Ana", "code": "NUEVO-9"}}
    client.patch(f"/cards/{control}", json=body, headers=KEY)
    card = client.get(f"/cards/{control}", headers=KEY).json()
    assert card["img"]["photo"] == uri and card["data"]["code"] == "NUEVO-9"


def test_revisions_are_bounded(client):
    control = _issued(client, "v0")["control"]
    for i in range(1, 26):
        client.patch(f"/cards/{control}", json=card_body(f"v{i}"), headers=KEY)
    revisions = client.get(f"/cards/{control}", headers=KEY).json()["revisions"]
    assert len(revisions) == 20 and revisions[-1]["data"]["name"] == "v24"


def test_voided_card_cannot_be_edited_and_unknown_is_404(client):
    control = _issued(client)["control"]
    client.post(f"/cards/{control}/void", headers=KEY)
    assert client.patch(f"/cards/{control}", json=card_body("X"), headers=KEY).status_code == 409
    assert client.patch("/cards/C-999999", json=card_body("X"), headers=KEY).status_code == 404


@pytest.mark.parametrize("body", [{"data": {"name": "x" * 201}, "tpl": {}}, {"tpl": {}, "data": {}, "control": "C-1"}, {"tpl": {}}])
def test_edit_is_validated(client, body):
    control = _issued(client)["control"]
    assert client.patch(f"/cards/{control}", json=body, headers=KEY).status_code == 422


def test_an_edited_card_still_round_trips_through_backup_restore(client):
    control = _issued(client, "Ana")["control"]
    client.patch(f"/cards/{control}", json=card_body("Ana B"), headers=KEY)
    backup = client.get("/cards?full=true", headers=KEY).json()[0]
    assert client.put("/cards/C-000900", json=backup, headers=KEY).status_code == 200


def test_web_files_are_revalidated_so_an_update_never_mixes_old_and_new(client):
    res = client.get("/ui/app.js")
    assert res.status_code == 200 and res.headers["cache-control"] == "no-cache" and res.headers.get("etag")
    assert client.get("/ui/app.js", headers={"If-None-Match": res.headers["etag"]}).status_code == 304


def test_pages_ask_for_assets_by_version(client):
    page = client.get("/ui/generador-carnets.html").text
    from app.version import VERSION
    for asset in ("/ui/app.css", "/ui/lib.js", "/ui/app.js"):
        assert f'"{asset}?v={VERSION}"' in page
    assert client.get(f"/ui/app.js?v={VERSION}").status_code == 200   # la consulta no estorba al archivo
