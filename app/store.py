import base64
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from pathlib import Path

logger = logging.getLogger("cardprint.store")
MAX_TEMPLATES = 200
MAX_CLIENTS = 500
MAX_REVISIONS = 20   # versiones anteriores que se recuerdan de un carnet corregido
_DATA_URI = re.compile(r"^data:image/(png|jpeg|webp|gif);base64,([A-Za-z0-9+/=]+)$")
_BLOB_REF = re.compile(r"^blob:([0-9a-f]{40}\.(?:png|jpg|webp|gif))$")
_EXT = {"png": "png", "jpeg": "jpg", "webp": "webp", "gif": "gif"}
_MIME = {"png": "png", "jpg": "jpeg", "webp": "webp", "gif": "gif"}
_CONTROL = re.compile(r"^C-(\d+)$")


class StoreError(ValueError):
    """Dato inválido o archivo dañado en el almacén."""


class NotFound(StoreError):
    """La plantilla o el carnet pedido no existe."""


class Conflict(StoreError):
    """La operación no aplica al estado actual (p. ej. editar un carnet anulado)."""


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


class ImageBlobs:
    """Imágenes de plantillas y carnets como archivos (`images/<sha1>.<ext>`), no dentro del JSON.

    Un logo que usan mil carnets se guarda una vez; los JSON guardan solo `blob:<archivo>`.
    """

    def __init__(self, folder: Path):
        self._folder = folder

    def externalize(self, obj):
        """Cambia cada `data:image/...;base64,...` por una referencia `blob:` (escribe el archivo)."""
        if isinstance(obj, str):
            match = _DATA_URI.match(obj)
            if not match:
                return obj
            try:
                data = base64.b64decode(match.group(2), validate=True)
            except ValueError as exc:
                raise StoreError("Imagen en base64 inválida") from exc
            name = f"{hashlib.sha1(data).hexdigest()}.{_EXT[match.group(1)]}"
            path = self._folder / name
            if not path.exists():
                self._folder.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_bytes(data)
                os.replace(tmp, path)
            return f"blob:{name}"
        if isinstance(obj, dict):
            return {k: self.externalize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.externalize(v) for v in obj]
        return obj

    def resolve(self, obj):
        """Inversa de `externalize`: devuelve las imágenes como data URI."""
        if isinstance(obj, str):
            match = _BLOB_REF.match(obj)
            if not match:
                return obj
            name = match.group(1)
            try:
                data = (self._folder / name).read_bytes()
            except OSError as exc:
                raise StoreError(f"Falta la imagen {name} en la carpeta images") from exc
            return f"data:image/{_MIME[name.rsplit('.', 1)[1]]};base64,{base64.b64encode(data).decode()}"
        if isinstance(obj, dict):
            return {k: self.resolve(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.resolve(v) for v in obj]
        return obj


class Store:
    """`templates.json`, `carnets.json`, `settings.json` y `clients.json` junto al .exe.

    Las imágenes viven aparte (`images/`); los JSON se pueden copiar o respaldar con esa carpeta.
    """

    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)   # una carpeta de datos nueva (CARDPRINT_DATA_DIR) también sirve
        self._blobs = ImageBlobs(data_dir / "images")
        self._templates = JsonFile(data_dir / "templates.json", {"active": None, "templates": {}})
        self._cards = JsonFile(data_dir / "carnets.json", {"cards": {}})
        self._settings = JsonFile(data_dir / "settings.json", {})
        self._clients = JsonFile(data_dir / "clients.json", {"clients": {}})
        self._drafts = JsonFile(data_dir / "draft.json", {"drafts": {}})
        self._card_dir = data_dir / "carnets"   # un JSON por carnet emitido (copia legible y portable)

    def compact(self) -> None:
        """Pasa a `images/` las imágenes que un JSON antiguo aún lleva dentro y da token a los
        perfiles de cliente creados antes de que existieran."""
        def add_tokens(data: dict) -> None:
            for client in data.get("clients", {}).values():
                client.setdefault("token", secrets.token_urlsafe(24))

        self._clients.update(add_tokens)
        for card in self._cards.read().get("cards", {}):   # carnets anteriores a los archivos por carnet
            if not (self._card_dir / f"{card}.json").exists():
                self._export_card(card)
        self._templates.update(lambda d: d.update(self._blobs.externalize(d)))
        self._cards.update(lambda d: d.update(self._blobs.externalize(d)))

    # --- plantillas ---
    def list_templates(self) -> dict:
        data = self._templates.read()
        return self._blobs.resolve({"active": data.get("active"), "templates": data.get("templates", {})})

    def get_template(self, template_id: str) -> dict:
        tpl = self.list_templates()["templates"].get(template_id)
        if tpl is None:
            raise NotFound("Plantilla no existe")
        return tpl

    def template_ids(self) -> set[str]:
        return set(self._templates.read().get("templates", {}))

    def active_template_id(self) -> str | None:
        return self._templates.read().get("active")

    def put_template(self, template_id: str, body: dict) -> dict:
        if not template_id.strip():
            raise StoreError("Falta el id de la plantilla")
        stored = self._blobs.externalize(body)

        def mutate(data: dict) -> None:
            templates = data.setdefault("templates", {})
            if template_id not in templates and len(templates) >= MAX_TEMPLATES:
                raise StoreError(f"Máximo {MAX_TEMPLATES} plantillas")
            templates[template_id] = stored
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
    @staticmethod
    def _light(card: dict) -> dict:
        return {k: v for k, v in card.items() if k != "img"}

    def list_cards(self, *, full: bool = False) -> list[dict]:
        cards = list(self._cards.read().get("cards", {}).values())
        return self._blobs.resolve(cards) if full else [self._light(c) for c in cards]

    def get_card(self, control: str) -> dict:
        card = self._cards.read().get("cards", {}).get(control)
        if card is None:
            raise NotFound("Carnet no existe")
        return self._blobs.resolve(card)

    def create_card(self, body: dict, template_id: str | None = None, created_by: str = "admin") -> dict:
        """Alta de un carnet: el servidor asigna control y código, así dos kioskos no chocan.
        `created_by` es «admin» o el id del perfil de kiosko (para «continuar desde el último»)."""
        stored = self._blobs.externalize(body)
        created: dict = {}

        def mutate(data: dict) -> None:
            cards = data.setdefault("cards", {})
            number = max((int(m.group(1)) for k in cards if (m := _CONTROL.match(k))), default=0) + 1
            card = {**stored, "control": f"C-{number:06d}", "createdAt": int(time.time() * 1000),
                    "prints": 1, "voided": False, "createdBy": created_by}
            if template_id:
                card["templateId"] = template_id
            info = card.setdefault("data", {})
            if not str(info.get("code", "")).strip():
                info["code"] = f"{card.get('tpl', {}).get('prefix', '')}{number:05d}"
            cards[card["control"]] = card
            created.update(card)

        self._cards.update(mutate)
        self._export_card(created["control"])
        return self._light(created)

    def put_card(self, control: str, body: dict) -> dict:
        """Alta o reemplazo con control explícito: solo para restaurar un respaldo."""
        if not control.strip():
            raise StoreError("Falta el número de control")
        stored = self._blobs.externalize({**body, "control": control})

        def mutate(data: dict) -> None:
            data.setdefault("cards", {})[control] = stored

        self._cards.update(mutate)
        self._export_card(control)
        return self._light(stored)

    def _change_card(self, control: str, change) -> dict:
        changed: dict = {}

        def mutate(data: dict) -> None:
            card = data.get("cards", {}).get(control)
            if card is None:
                raise NotFound("Carnet no existe")
            change(card)
            changed.update(card)

        self._cards.update(mutate)
        self._export_card(control)
        return self._light(changed)

    def update_card(self, control: str, body: dict, by: str = "admin") -> dict:
        """Corrige un carnet: cambia sus datos, plantilla e imágenes pero conserva control, código (si
        el nuevo viene vacío), fecha de alta, quién lo emitió y reimpresiones. Guarda lo anterior en
        `revisions` para poder ver qué se corrigió. Un carnet anulado no se edita."""
        stored = self._blobs.externalize(body)
        changed: dict = {}

        def mutate(data: dict) -> None:
            card = data.get("cards", {}).get(control)
            if card is None:
                raise NotFound("Carnet no existe")
            if card.get("voided"):
                raise Conflict("Un carnet anulado no se puede editar; emite uno nuevo")
            new_data = dict(stored.get("data", {}))
            if not str(new_data.get("code", "")).strip():
                new_data["code"] = card.get("data", {}).get("code", "")
            revisions = [*card.get("revisions", []),
                         {"at": int(time.time() * 1000), "by": by, "data": card.get("data", {})}]
            card.update({k: v for k, v in stored.items() if k in ("tpl", "img")})
            card["data"] = new_data
            card["revisions"] = revisions[-MAX_REVISIONS:]
            card["updatedAt"], card["updatedBy"] = revisions[-1]["at"], by
            if "templateId" in stored:
                card["templateId"] = stored["templateId"]
            changed.update(card)

        self._cards.update(mutate)
        self._export_card(control)
        return self._light(changed)

    def reprint_card(self, control: str) -> dict:
        return self._change_card(control, lambda c: c.__setitem__("prints", int(c.get("prints", 1)) + 1))

    def void_card(self, control: str) -> dict:
        return self._change_card(control, lambda c: c.__setitem__("voided", True))

    def last_card(self, created_by: str | None = None) -> dict:
        """El último carnet emitido (completo, con imágenes). `created_by` limita a los de ese
        administrador o kiosko; sin él, el último de todos."""
        cards = [c for c in self._cards.read().get("cards", {}).values()
                 if created_by is None or c.get("createdBy", "admin") == created_by]
        if not cards:
            raise NotFound("Aún no hay carnets emitidos")
        newest = max(cards, key=lambda c: (c.get("createdAt", 0), c.get("control", "")))
        return self._blobs.resolve(newest)

    def _export_card(self, control: str) -> None:
        """Copia del carnet como `carnets/<control>.json`, autocontenida (imágenes incluidas) y legible.
        La fuente de verdad es carnets.json: si la copia no se puede escribir se avisa en el log
        y el carnet queda registrado igual."""
        try:
            card = self.get_card(control)
            self._card_dir.mkdir(parents=True, exist_ok=True)
            path = self._card_dir / f"{control}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except (OSError, StoreError):
            logger.exception("No se pudo escribir la copia del carnet %s", control)

    # --- borrador del titular (lo que se está llenando): uno por administrador y por kiosko ---
    def get_draft(self, key: str) -> dict:
        return self._blobs.resolve(self._drafts.read().get("drafts", {}).get(key, {}))

    def put_draft(self, key: str, body: dict) -> dict:
        stored = self._blobs.externalize(body)

        def mutate(data: dict) -> None:
            drafts = data.setdefault("drafts", {})
            if key not in drafts and len(drafts) > MAX_CLIENTS:
                raise StoreError("Demasiados borradores")
            drafts[key] = stored

        self._drafts.update(mutate)
        return body

    def delete_draft(self, key: str) -> None:
        self._drafts.update(lambda data: data.setdefault("drafts", {}).pop(key, None))

    # --- ajustes de la UI (impresora, desplazamientos, calidad...): settings.json ---
    def get_settings(self) -> dict:
        return self._settings.read()

    def put_settings(self, body: dict) -> dict:
        def mutate(data: dict) -> None:
            data.clear()
            data.update(body)

        return self._settings.update(mutate)

    # --- clientes (modo kiosko): plantilla fija + campos editables + token propio ---
    def _clients_raw(self) -> dict:
        return self._clients.read().get("clients", {})

    def list_clients(self) -> dict:
        """Perfiles sin su token (el token solo sale en la página del kiosko)."""
        return {cid: {k: v for k, v in c.items() if k != "token"} for cid, c in self._clients_raw().items()}

    def get_client(self, client_id: str) -> dict:
        client = self._clients_raw().get(client_id)
        if client is None:
            raise NotFound("Cliente no existe")
        return client

    def client_for_token(self, token: str) -> tuple[str, dict] | None:
        if not token:
            return None
        found = None
        for cid, client in self._clients_raw().items():  # sin cortar: tiempo constante
            if secrets.compare_digest(str(client.get("token", "")).encode(), token.encode()):
                found = (cid, client)
        return found

    def put_client(self, client_id: str, body: dict) -> dict:
        saved: dict = {}

        def mutate(data: dict) -> None:
            clients = data.setdefault("clients", {})
            if client_id not in clients and len(clients) >= MAX_CLIENTS:
                raise StoreError(f"Máximo {MAX_CLIENTS} clientes")
            token = clients.get(client_id, {}).get("token") or secrets.token_urlsafe(24)
            clients[client_id] = {**body, "token": token}
            saved.update(clients[client_id])

        self._clients.update(mutate)
        return {k: v for k, v in saved.items() if k != "token"}

    def delete_client(self, client_id: str) -> None:
        def mutate(data: dict) -> None:
            if client_id not in data.get("clients", {}):
                raise NotFound("Cliente no existe")
            del data["clients"][client_id]

        self._clients.update(mutate)
