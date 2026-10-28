import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app

KEY = {"X-API-Key": "secret"}
TPL = {"org": "ACME", "prefix": "GAG-"}


def png_bytes(size=(1011, 638), color=(255, 0, 0, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def data_uri(color=(10, 20, 30, 255), size=(8, 8)) -> str:
    return "data:image/png;base64," + base64.b64encode(png_bytes(size, color)).decode()


def card_body(name="Ana", **overrides) -> dict:
    body = {"tpl": TPL, "data": {"name": name, "ced": "001-1234567-8", "issue": "2026-10-28"}, "img": {}}
    return body | overrides


@pytest.fixture
def make_app(tmp_path):
    def build(**overrides):
        printers = tmp_path / "printers.yaml"
        printers.write_text(
            "printers:\n  - {id: mock, label: Mock, adapter: mock,"
            " allowed_options: {RibbonName: [15Hologram, 0YMCKO], Free: []}}\n"
        )
        options = {"data_dir": tmp_path, "max_upload_bytes": 200_000, **overrides}
        return create_app(Settings(api_key="secret", printers_file=printers, **options))
    return build


@pytest.fixture
def client(make_app):
    with TestClient(make_app()) as c:
        yield c
