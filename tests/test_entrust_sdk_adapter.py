import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.printers import entrust_sdk
from app.printers.base import PrintError, PrintRequest
from app.printers.entrust_sdk import EntrustSdkAdapter

pytest.importorskip("pypdfium2")


@pytest.fixture
def bridge(tmp_path):
    exe = tmp_path / "CardBridge.exe"
    exe.write_text("")
    return str(exe)


@pytest.fixture
def pdf(tmp_path):
    faces = [Image.new("RGB", (1011, 638), c) for c in ("red", "blue")]
    path = tmp_path / "card.pdf"
    faces[0].save(path, format="PDF", resolution=300, save_all=True, append_images=faces[1:])
    return path


def _fake_run(calls, reply):
    def run(cmd, **kw):
        calls.append(cmd)
        for flag in ("--front", "--back"):
            if flag in cmd:
                assert Path(cmd[cmd.index(flag) + 1]).exists()
        return subprocess.CompletedProcess(cmd, 0, json.dumps(reply) + "\n", "")
    return run


def test_submit_renders_faces_and_maps_options(monkeypatch, bridge, pdf):
    calls = []
    monkeypatch.setattr(entrust_sdk.subprocess, "run", _fake_run(calls, {"ok": True, "printerJobId": 7}))
    opts = {"rotate_back": "true", "rotate_front": "false", "topcoat_front": "all"}
    job = EntrustSdkAdapter("XPS Card Printer", bridge).submit(PrintRequest(pdf, 2, opts))
    assert job == "entrust:7,7"
    cmd = calls[0]
    assert cmd[:2] == [bridge, "print"]
    assert "--rotate-back" in cmd and "--rotate-front" not in cmd
    assert cmd[cmd.index("--topcoat-front") + 1] == "all"
    assert "--front" in cmd and "--back" in cmd
    assert cmd[cmd.index("--printer") + 1] == "XPS Card Printer"


def test_submit_raises_printer_error(monkeypatch, bridge, pdf):
    monkeypatch.setattr(entrust_sdk.subprocess, "run", _fake_run([], {"ok": False, "error": "sin tarjetas"}))
    with pytest.raises(PrintError, match="sin tarjetas"):
        EntrustSdkAdapter("P", bridge).submit(PrintRequest(pdf, 1, {}))


def test_submit_rejects_unknown_option(bridge, pdf):
    with pytest.raises(PrintError, match="no soportada"):
        EntrustSdkAdapter("P", bridge).submit(PrintRequest(pdf, 1, {"RibbonName": "x"}))


def test_missing_bridge(tmp_path, pdf):
    with pytest.raises(PrintError, match="CardBridge"):
        EntrustSdkAdapter("P", str(tmp_path / "nope.exe")).submit(PrintRequest(pdf, 1, {}))


@pytest.mark.parametrize(
    "reply,expected",
    [({"ok": True, "ready": True}, "ready"), ({"ok": True, "ready": False}, "offline"), ({"ok": False}, "offline")],
)
def test_status(monkeypatch, bridge, reply, expected):
    monkeypatch.setattr(entrust_sdk.subprocess, "run", _fake_run([], reply))
    assert EntrustSdkAdapter("P", bridge).status() == expected


def test_status_unknown_on_garbage(monkeypatch, bridge):
    monkeypatch.setattr(
        entrust_sdk.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, -1, "not json", "boom"),
    )
    assert EntrustSdkAdapter("P", bridge).status() == "unknown"
