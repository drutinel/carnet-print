import subprocess
from pathlib import Path

import pytest

from app.printers import windows
from app.printers.base import PrintError, PrintRequest
from app.printers.windows import WindowsAdapter


@pytest.fixture
def sumatra(tmp_path):
    exe = tmp_path / "SumatraPDF.exe"
    exe.write_text("")
    return str(exe)


def _request(options=None, copies=2):
    return PrintRequest(pdf_path=Path("card.pdf"), copies=copies, options=options or {})


def test_submit_builds_sumatra_command(monkeypatch, sumatra):
    calls = []
    monkeypatch.setattr(windows.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    job = WindowsAdapter("Entrust Sigma DS3 Card Printer", sumatra).submit(_request())
    cmd = calls[0]
    assert cmd[:3] == [sumatra, "-print-to", "Entrust Sigma DS3 Card Printer"]
    assert "noscale,2x" in cmd and cmd[-1] == "card.pdf"
    assert job.startswith("windows:")


def test_submit_rejects_per_job_options(sumatra):
    with pytest.raises(PrintError):
        WindowsAdapter("P", sumatra).submit(_request({"RibbonName": "x"}))


def test_submit_fails_without_sumatra(tmp_path):
    with pytest.raises(PrintError, match="SumatraPDF"):
        WindowsAdapter("P", str(tmp_path / "missing.exe")).submit(_request())


def test_submit_wraps_sumatra_error(monkeypatch, sumatra):
    def boom(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd, stderr="printer not found")

    monkeypatch.setattr(windows.subprocess, "run", boom)
    with pytest.raises(PrintError, match="printer not found"):
        WindowsAdapter("P", sumatra).submit(_request())


@pytest.mark.parametrize(
    "rc,stdout,expected", [(0, "Normal\n", "ready"), (0, "Offline\n", "offline"), (1, "", "offline")]
)
def test_status(monkeypatch, sumatra, rc, stdout, expected):
    monkeypatch.setattr(
        windows.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, rc, stdout, ""),
    )
    assert WindowsAdapter("P", sumatra).status() == expected


def test_status_passes_printer_name(monkeypatch, sumatra):
    seen = {}

    def run(cmd, **kw):
        seen.update(cmd=cmd, env=kw.get("env", {}))
        return subprocess.CompletedProcess(cmd, 0, "Normal\n", "")

    monkeypatch.setattr(windows.subprocess, "run", run)
    WindowsAdapter("Zebra ZC300 USB Card Printer", sumatra).status()
    assert seen["env"]["CARDPRINT_PRINTER"] == "Zebra ZC300 USB Card Printer"
    assert "$env:CARDPRINT_PRINTER" in seen["cmd"][-1]
