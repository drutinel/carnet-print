import json
import subprocess

import pytest

from app.printers import bridge, entrust_sdk, zebra_sdk
from app.printers.base import PrintError, PrintRequest
from app.printers.entrust_sdk import EntrustSdkAdapter
from app.printers.errors import ENTRUST_MESSAGES, error_code, operator_message
from app.printers.zebra_sdk import ZebraSdkAdapter


@pytest.fixture
def exe(tmp_path):
    path = tmp_path / "Bridge.exe"
    path.write_text("")
    return str(path)


@pytest.fixture
def faces(tmp_path):
    out = {}
    for key in ("front", "back"):
        out[key] = tmp_path / f"{key}.png"
        out[key].write_bytes(b"png")
    return out


def _run(calls, reply):
    def run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 1, json.dumps(reply) + "\n", "")
    return run


def test_error_code_prefers_field_then_text():
    assert error_code({"errorCode": 113, "error": "112 x"}) == 113
    assert error_code({"error": "StartJob(): 112 Card hopper empty"}) == 112
    assert error_code({"error": "tiempo agotado"}) is None


def test_operator_message_known_code_keeps_detail():
    msg = operator_message("SDK de Entrust", ENTRUST_MESSAGES, {"error": "112 Card hopper empty (severidad 4)"})
    assert msg.startswith("Sin tarjetas en la tolva: cargue tarjetas y reintente.")
    assert "[112 Card hopper empty" in msg


def test_operator_message_unknown_code_and_not_recovered():
    msg = operator_message("SDK de Entrust", ENTRUST_MESSAGES,
                           {"error": "999 Raro", "errorCode": 999, "recovered": False})
    assert msg.startswith("SDK de Entrust: 999 Raro")
    assert "no se resolvió a tiempo" in msg


@pytest.mark.parametrize(
    "adapter_cls,module,reply,expected",
    [
        (EntrustSdkAdapter, entrust_sdk,
         {"ok": False, "error": "113 Close cover to continue (severidad 4)", "errorCode": 113, "recovered": False},
         "Tapa abierta"),
        (ZebraSdkAdapter, zebra_sdk,
         {"ok": False, "error": "4016 Card feeder is empty", "errorCode": 4016},
         "Sin tarjetas en el alimentador"),
    ],
)
def test_submit_raises_operator_message(monkeypatch, exe, faces, adapter_cls, module, reply, expected):
    calls = []
    monkeypatch.setattr(module.subprocess, "run", _run(calls, reply))
    with pytest.raises(PrintError, match=expected):
        adapter_cls("P", exe).submit(PrintRequest(None, 1, {}, faces=faces))


def test_print_passes_recover_wait_and_covers_it_in_timeout(monkeypatch, exe, faces):
    calls = []
    monkeypatch.setattr(entrust_sdk.subprocess, "run", _run(calls, {"ok": True, "printerJobId": 5}))
    EntrustSdkAdapter("P", exe).submit(PrintRequest(None, 1, {}, faces=faces))
    cmd, kw = calls[0]
    assert cmd[cmd.index("--recover-wait") + 1] == str(bridge.RECOVER_WAIT_S)
    bridge_timeout = int(cmd[cmd.index("--timeout") + 1])
    assert bridge_timeout >= bridge.RECOVER_WAIT_S + 120
    assert kw["timeout"] > bridge_timeout


def test_status_does_not_pass_recover_wait(monkeypatch, exe):
    calls = []
    monkeypatch.setattr(entrust_sdk.subprocess, "run", _run(calls, {"ok": True, "ready": True}))
    EntrustSdkAdapter("P", exe).status()
    assert "--recover-wait" not in calls[0][0]
