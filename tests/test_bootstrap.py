from app.bootstrap import ensure_config
from app.config import load_printers


def test_first_run_creates_config_with_random_key(tmp_path):
    key = ensure_config(tmp_path)
    assert key and len(key) >= 24
    assert f"CARDPRINT_API_KEY={key}" in (tmp_path / ".env").read_text(encoding="utf-8")
    printers = load_printers(tmp_path / "printers.yaml")
    assert [p.adapter for p in printers] == ["entrust-sdk"]


def test_existing_config_is_left_alone(tmp_path):
    ensure_config(tmp_path)
    (tmp_path / "printers.yaml").write_text("printers: []\n", encoding="utf-8")
    assert ensure_config(tmp_path) is None
    assert (tmp_path / "printers.yaml").read_text(encoding="utf-8") == "printers: []\n"
