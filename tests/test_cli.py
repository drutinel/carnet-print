import json
import socket
import threading
import time

import pytest
import uvicorn

from app import cli
from app.config import Settings
from app.main import create_app
from conftest import png_bytes


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def settings(tmp_path):
    (tmp_path / "printers.yaml").write_text(
        "printers:\n  - {id: mock, label: Mock, adapter: mock,"
        " allowed_options: {print_mode: [custom, standard], color_dpi: ['300x300'], mono_dpi: ['300x600'],"
        " hopper: ['1', '2'], split_ribbon: [ymct_k]}}\n")
    return Settings(api_key="secret", printers_file=tmp_path / "printers.yaml", data_dir=tmp_path, port=_free_port())


@pytest.fixture
def faces(tmp_path):
    out = tmp_path / "in"
    out.mkdir()
    for name, color in (("front", (255, 0, 0, 255)), ("back", (0, 0, 255, 255))):
        (out / f"{name}.png").write_bytes(png_bytes((1015, 640), color))
    return out


def run(settings, *argv) -> int:
    return cli.main(list(argv), settings)


def test_print_two_faces_directly(settings, faces, tmp_path, capsys):
    code = run(settings, "print", "--front", str(faces / "front.png"), "--back", str(faces / "back.png"), "--control", "C-000009")
    out = capsys.readouterr()
    assert code == 0 and "Enviado a Mock" in out.out and "C-000009" in out.out
    archived = next((tmp_path / "png").glob("*_C-000009"))
    assert {p.name for p in archived.iterdir()} == {"front.png", "back.png"}


def test_json_output_is_one_parseable_line(settings, faces, capsys):
    code = run(settings, "print", "--json", "--front", str(faces / "front.png"), "--back", str(faces / "back.png"))
    lines = capsys.readouterr().out.strip().splitlines()
    assert code == 0 and len(lines) == 1
    result = json.loads(lines[0])
    assert result["ok"] and result["state"] == "submitted" and result["printer"] == "mock" and result["via"] == "directo"


def test_reprint_an_archived_folder_and_a_card(settings, faces, tmp_path, capsys):
    run(settings, "print", "--front", str(faces / "front.png"), "--back", str(faces / "back.png"), "--control", "C-000001")
    folder = next((tmp_path / "png").glob("*_C-000001"))
    assert run(settings, "print", "--png-dir", str(folder)) == 0
    # un carnet registrado: se reimprime con su PNG archivado y cuenta la reimpresión
    from app.store import Store
    store = Store(tmp_path)
    created = store.create_card({"tpl": {}, "data": {"name": "Ana"}, "img": {}})
    shutil_copy = tmp_path / "png" / f"20260101-000000_{created['control']}"
    shutil_copy.mkdir()
    for name in ("front.png", "back.png"):
        (shutil_copy / name).write_bytes((folder / name).read_bytes())
    assert run(settings, "print", "--card", created["control"]) == 0
    assert store.get_card(created["control"])["prints"] == 2
    capsys.readouterr()


def test_failed_reprint_does_not_count(settings, tmp_path, monkeypatch, capsys):
    from app.printers import mock
    from app.printers.base import PrintError
    from app.store import Store
    store = Store(tmp_path)
    control = store.create_card({"tpl": {}, "data": {"name": "Ana"}, "img": {}})["control"]
    folder = tmp_path / "png" / f"20260101-000000_{control}"
    folder.mkdir(parents=True)
    for name in ("front.png", "back.png"):
        (folder / name).write_bytes(png_bytes((1015, 640)))
    monkeypatch.setattr(mock.MockAdapter, "submit", lambda self, request: (_ for _ in ()).throw(PrintError("Sin tarjetas en la tolva")))
    assert run(settings, "print", "--card", control) == cli.EXIT_FAILED
    assert "Sin tarjetas" in capsys.readouterr().err
    assert store.get_card(control)["prints"] == 1


@pytest.mark.parametrize(
    "argv,message",
    [
        (["print"], "una sola fuente"),
        (["print", "--front", "x.png"], "van juntos"),
        (["print", "--front", "no.png", "--back", "no.png"], "No existe el archivo"),
        (["print", "--png-dir", "no-existe"], "No existe la carpeta"),
        (["print", "--card", "C-424242"], "No hay PNG archivados"),
        (["print", "--png-dir", ".", "--card", "C-1"], "una sola fuente"),
    ],
)
def test_invalid_input_exits_with_2_and_a_clear_message(settings, capsys, argv, message):
    assert run(settings, *argv) == cli.EXIT_INVALID
    assert message in capsys.readouterr().err


def test_bad_options_copies_and_printer(settings, faces, capsys):
    base = ["print", "--front", str(faces / "front.png"), "--back", str(faces / "back.png")]
    assert run(settings, *base, "--copies", "99") == cli.EXIT_INVALID
    assert run(settings, *base, "--option", "sinvalor") == cli.EXIT_INVALID
    assert run(settings, *base, "--option", "print_mode=explotar") == cli.EXIT_INVALID
    assert run(settings, *base, "--printer", "nope") == cli.EXIT_INVALID
    assert "no existe" in capsys.readouterr().err


def test_not_a_png_is_rejected(settings, tmp_path, capsys):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"no soy un png")
    assert run(settings, "print", "--front", str(bad), "--back", str(bad)) == cli.EXIT_INVALID


def test_options_come_from_settings_json_like_the_web(settings, faces, tmp_path, monkeypatch):
    (tmp_path / "settings.json").write_text(json.dumps(
        {"quality": "fine", "hopper": "2", "cal": {"mock": {"split": True}}}))
    seen = []
    from app.printers import mock
    monkeypatch.setattr(mock.MockAdapter, "submit", lambda self, request: seen.append(dict(request.options)) or "m-1")
    base = ["print", "--front", str(faces / "front.png"), "--back", str(faces / "back.png")]
    assert run(settings, *base) == 0
    assert seen[-1] == {"print_mode": "custom", "color_dpi": "300x300", "mono_dpi": "300x600", "hopper": "2", "split_ribbon": "ymct_k"}
    assert run(settings, *base, "--option", "print_mode=standard") == 0   # --option reemplaza las de Avanzado
    assert seen[-1] == {"print_mode": "standard"}


def test_printers_lists_them(settings, capsys):
    assert run(settings, "printers", "--json") == 0
    assert json.loads(capsys.readouterr().out) == [{"id": "mock", "label": "Mock", "status": "ready"}]


def test_multipart_encoding():
    body, ctype = cli.encode_multipart({"printer_id": "mock"}, {"front": b"\x89PNG"})
    boundary = ctype.split("boundary=")[1]
    assert body.startswith(f"--{boundary}".encode()) and b'name="printer_id"\r\n\r\nmock' in body
    assert b'name="front"; filename="front.png"' in body and body.endswith(f"--{boundary}--\r\n".encode())


@pytest.fixture
def running_server(settings):
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=settings.port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield server
    server.should_exit = True
    thread.join(5)


def test_uses_the_open_program_when_it_is_running(settings, faces, running_server, capsys):
    assert cli.server_running(settings)
    code = run(settings, "print", "--json", "--front", str(faces / "front.png"), "--back", str(faces / "back.png"), "--control", "C-000077")
    result = json.loads(capsys.readouterr().out.strip())
    assert code == 0 and result["via"] == "programa abierto" and result["pngDir"].endswith("_C-000077")
    assert run(settings, "printers", "--json") == 0


def test_a_wrong_api_key_is_reported(settings, faces, running_server, capsys):
    wrong = Settings(api_key="otra", printers_file=settings.printers_file, data_dir=settings.data_dir, port=settings.port)
    assert run(wrong, "print", "--front", str(faces / "front.png"), "--back", str(faces / "back.png")) == cli.EXIT_INVALID
    assert "401" in capsys.readouterr().err


def test_server_running_is_false_when_nothing_listens(settings):
    assert cli.server_running(settings) is False
