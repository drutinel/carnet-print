import json
import os
import threading
from pathlib import Path


class StoreError(ValueError):
    """Dato inválido o archivo dañado en el almacén."""


class NotFound(StoreError):
    """La plantilla o el carnet pedido no existe."""


class JsonFile:
    """Un archivo JSON con escritura atómica (temporal + os.replace) y un lock por archivo."""

    def __init__(self, path: Path, default: dict):
        self._path = path
        self._default = default
        self._lock = threading.RLock()

    def read(self) -> dict:
        with self._lock:
            if not self._path.exists():
                return json.loads(json.dumps(self._default))
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise StoreError(f"{self._path.name} está dañado: {exc}") from exc
            if not isinstance(data, dict):
                raise StoreError(f"{self._path.name} debe ser un objeto JSON")
            return data

    def update(self, mutate) -> dict:
        """Lee, aplica `mutate(data)` y guarda; devuelve lo guardado."""
        with self._lock:
            data = self.read()
            mutate(data)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self._path)
            return data


class Store:
    """`templates.json` (plantillas + cuál usa el API) y `carnets.json` (generados).

    Ambos viven en `data_dir` (junto al .exe) y se pueden copiar o respaldar tal cual.
    """

    def __init__(self, data_dir: Path):
        self._templates = JsonFile(
            data_dir / "templates.json", {"active": None, "templates": {}}
        )
        self._cards = JsonFile(data_dir / "carnets.json", {"cards": {}})

    # --- plantillas ---
    def list_templates(self) -> dict:
        data = self._templates.read()
        return {"active": data.get("active"), "templates": data.get("templates", {})}

    def get_template(self, template_id: str) -> dict:
        tpl = self.list_templates()["templates"].get(template_id)
        if tpl is None:
            raise NotFound("Plantilla no existe")
        return tpl

    def active_template_id(self) -> str | None:
        return self.list_templates()["active"]

    def put_template(self, template_id: str, body: dict) -> dict:
        if not template_id.strip():
            raise StoreError("Falta el id de la plantilla")

        def mutate(data: dict) -> None:
            data.setdefault("templates", {})[template_id] = body
            if not data.get("active"):
                data["active"] = template_id  # la primera plantilla queda activa

        self._templates.update(mutate)
        return body

    def delete_template(self, template_id: str) -> None:
        def mutate(data: dict) -> None:
            templates = data.setdefault("templates", {})
            if template_id not in templates:
                raise NotFound("Plantilla no existe")
            del templates[template_id]
            if data.get("active") == template_id:
                data["active"] = next(iter(templates), None)

        self._templates.update(mutate)

    def activate_template(self, template_id: str) -> None:
        def mutate(data: dict) -> None:
            if template_id not in data.get("templates", {}):
                raise NotFound("Plantilla no existe")
            data["active"] = template_id

        self._templates.update(mutate)

    # --- carnets generados ---
    def list_cards(self) -> list[dict]:
        return list(self._cards.read().get("cards", {}).values())

    def put_card(self, control: str, body: dict) -> dict:
        if not control.strip():
            raise StoreError("Falta el número de control")

        def mutate(data: dict) -> None:
            data.setdefault("cards", {})[control] = body

        self._cards.update(mutate)
        return body
