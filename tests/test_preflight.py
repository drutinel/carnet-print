import subprocess

import pytest
from fastapi.testclient import TestClient

from app.config import PrinterConfig, Settings
from app.main import create_app
from app.preflight import DOTNET_URL, DRIVER_URL, desktop_runtime_major, failed, run_checks

DS3 = PrinterConfig(id="ds3", label="DS3", adapter="entrust-sdk", printer_name="XPS Card Printer")


@pytest.fixture
def program_files(tmp_path):
    root = tmp_path / "dotnet" / "shared" / "Microsoft.WindowsDesktop.App"
    (root / "8.0.11").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def bridge(tmp_path):
    exe = tmp_path / "CardBridge.exe"
    exe.write_text("")
    return PrinterConfig(**{**DS3.model_dump(), "bridge_path": str(exe)})


def test_all_good_reports_nothing(program_files, bridge):
    checks = run_checks([bridge], platform="win32", program_files=program_files,
                        printer_driver=lambda name: "XPS Card Printer Driver")
    assert failed(checks) == []


def test_missing_dotnet_links_to_download(tmp_path, bridge):
    checks = run_checks([bridge], platform="win32", program_files=tmp_path,
                        printer_driver=lambda name: "x")
    assert [(c["id"], c["url"]) for c in failed(checks)] == [("dotnet", DOTNET_URL)]


def test_old_dotnet_is_not_enough(tmp_path, bridge):
    (tmp_path / "dotnet" / "shared" / "Microsoft.WindowsDesktop.App" / "6.0.30").mkdir(parents=True)
    assert desktop_runtime_major(tmp_path) == 6
    assert [c["id"] for c in failed(run_checks(
        [bridge], platform="win32", program_files=tmp_path, printer_driver=lambda n: "x"))] == ["dotnet"]


def test_missing_printer_links_to_driver(program_files, bridge):
    checks = run_checks([bridge], platform="win32", program_files=program_files,
                        printer_driver=lambda name: None)
    [problem] = failed(checks)
    assert problem["id"] == "printer:ds3" and problem["url"] == DRIVER_URL
    assert "XPS Card Printer" in problem["detail"]


def test_missing_bridge_is_reported(program_files, tmp_path):
    cfg = PrinterConfig(**{**DS3.model_dump(), "bridge_path": str(tmp_path / "nope.exe")})
    checks = run_checks([cfg], platform="win32", program_files=program_files,
                        printer_driver=lambda name: "x")
    assert [c["id"] for c in failed(checks)] == ["bridge:ds3"]


def test_powershell_failure_is_reported_not_swallowed(program_files, bridge):
    def boom(name):
        raise subprocess.TimeoutExpired("powershell", 15)
    [problem] = failed(run_checks([bridge], platform="win32", program_files=program_files,
                                  printer_driver=boom))
    assert "PowerShell" in problem["detail"]


def test_nothing_to_check_outside_windows_or_without_entrust(program_files, bridge):
    assert run_checks([bridge], platform="darwin") == []
    assert run_checks([PrinterConfig(id="m", label="M", adapter="mock")], platform="win32") == []


def test_preflight_endpoint_is_public(tmp_path):
    printers = tmp_path / "printers.yaml"
    printers.write_text("printers:\n  - {id: mock, label: Mock, adapter: mock}\n")
    app = create_app(Settings(api_key="secret", printers_file=printers, data_dir=tmp_path))
    with TestClient(app) as c:
        assert c.get("/preflight").json() == []


def test_windows_printer_driver_reads_powershell_output(monkeypatch):
    from app import preflight
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["env"] = kwargs["env"]["CARDPRINT_CHECK_PRINTER"]
        return subprocess.CompletedProcess(cmd, 0, "Entrust XPS Card Printer Driver\r\n", "")

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    assert preflight.windows_printer_driver("XPS Card Printer") == "Entrust XPS Card Printer Driver"
    assert seen["env"] == "XPS Card Printer"   # el nombre viaja por entorno, no pegado al comando


def test_windows_printer_driver_is_none_when_powershell_fails(monkeypatch):
    from app import preflight
    monkeypatch.setattr(
        preflight.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "no existe"))
    assert preflight.windows_printer_driver("Inexistente") is None
