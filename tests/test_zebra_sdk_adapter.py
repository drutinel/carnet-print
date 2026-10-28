import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.printers import zebra_sdk
from app.printers.base import PrintError, PrintRequest
from app.printers.zebra_sdk import ZebraSdkAdapter


@pytest.fixture
def bridge(tmp_path):
    exe = tmp_path / "ZebraBridge.exe"
    exe.write_text("")
    return str(exe)


@pytest.fixture
def pdf(tmp_path):
    """Caras PNG tal como las recibe el puente (nombre `pdf` por los tests existentes)."""
    faces = {}
    for key, color in (("front", "red"), ("back", "blue")):
        faces[key] = tmp_path / f"{key}.png"
        Image.new("RGB", (1011, 638), color).save(faces[key])
    return faces


def _fake_run(calls, reply):
    def run(cmd, **kw):
        calls.append(cmd)
        for flag in ("--front", "--back"):
            if flag in cmd:
                assert Path(cmd[cmd.index(flag) + 1]).exists()
        return subprocess.CompletedProcess(cmd, 0, json.dumps(reply) + "\n", "")
    return run


def test_submit_maps_options_and_faces(monkeypatch, bridge, pdf):
    calls = []
    monkeypatch.setattr(zebra_sdk.subprocess, "run", _fake_run(calls, {"ok": True, "printerJobId": 12}))
    opts = {"back_type": "mono", "overlay_back": "false"}
    job = ZebraSdkAdapter("Zebra ZC300 USB Card Printer", bridge).submit(PrintRequest(None, 1, opts, faces=pdf))
    assert job == "zebra:12"
    cmd = calls[0]
    assert cmd[:2] == [bridge, "print"]
    assert cmd[cmd.index("--back-type") + 1] == "mono"
    assert cmd[cmd.index("--overlay-back") + 1] == "false"
    assert "--front" in cmd and "--back" in cmd


def test_submit_raises_printer_error(monkeypatch, bridge, pdf):
    monkeypatch.setattr(zebra_sdk.subprocess, "run", _fake_run([], {"ok": False, "error": "4003 Out of cards"}))
    with pytest.raises(PrintError, match="Out of cards"):
        ZebraSdkAdapter("P", bridge).submit(PrintRequest(None, 1, {}, faces=pdf))


def test_submit_rejects_unknown_option(bridge, pdf):
    with pytest.raises(PrintError, match="no soportada"):
        ZebraSdkAdapter("P", bridge).submit(PrintRequest(None, 1, {"RibbonName": "x"}, faces=pdf))


def test_missing_bridge(tmp_path, pdf):
    with pytest.raises(PrintError, match="ZebraBridge"):
        ZebraSdkAdapter("P", str(tmp_path / "ZebraBridge.exe")).submit(PrintRequest(None, 1, {}, faces=pdf))


@pytest.mark.parametrize(
    "reply,expected",
    [({"ok": True, "ready": True}, "ready"), ({"ok": True, "ready": False}, "offline"),
     ({"ok": False, "error": "no hay ninguna impresora"}, "offline")],
)
def test_status(monkeypatch, bridge, reply, expected):
    monkeypatch.setattr(zebra_sdk.subprocess, "run", _fake_run([], reply))
    assert ZebraSdkAdapter("P", bridge).status() == expected


def test_copies_go_in_one_job(monkeypatch, bridge, pdf):
    calls = []
    monkeypatch.setattr(zebra_sdk.subprocess, "run", _fake_run(calls, {"ok": True, "printerJobId": 5}))
    job = ZebraSdkAdapter("P", bridge).submit(PrintRequest(None, 3, {"auto_k": "true"}, faces=pdf))
    assert job == "zebra:5"
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[cmd.index("--copies") + 1] == "3"
    assert "--auto-k" in cmd


def test_single_copy_has_no_copies_flag(monkeypatch, bridge, pdf):
    calls = []
    monkeypatch.setattr(zebra_sdk.subprocess, "run", _fake_run(calls, {"ok": True, "printerJobId": 6}))
    ZebraSdkAdapter("P", bridge).submit(PrintRequest(None, 1, {"auto_k": "false"}, faces=pdf))
    assert "--copies" not in calls[0] and "--auto-k" not in calls[0]


def test_registry_builds_zebra_adapter():
    from app.config import PrinterConfig
    from app.printers.registry import build_adapter

    cfg = PrinterConfig(id="z", label="Z", adapter="zebra-sdk", printer_name="Zebra ZC300 USB Card Printer")
    assert isinstance(build_adapter(cfg), ZebraSdkAdapter)
