# Card Print Middleware

API HTTP en Linux (FastAPI) que recibe un PDF de carnet desde la webapp y lo imprime en
**Zebra ZC300** y **Entrust Sigma DS3** vía CUPS.

```
Webapp ──HTTPS──▶ (reverse proxy) ──▶ FastAPI :8080 ──▶ cola serial por impresora ──▶ lp ──▶ CUPS ──▶ impresora
```

## Uso

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env && cp printers.example.yaml printers.yaml   # editar
.venv/bin/uvicorn app.main:create_app --factory --port 8080
.venv/bin/pytest
```

| Endpoint | Descripción |
|---|---|
| `GET /health` | Público |
| `GET /printers` | Impresoras y estado (`ready`/`offline`/`unknown`) |
| `POST /jobs` | multipart: `printer_id`, `pdf` **o** `front`+`back` (PNG 300 ppp, el middleware arma el PDF CR80), `copies` (1-10), `options` (JSON). Devuelve 202 + job |
| `GET /printers/{id}/options` | Opciones CUPS permitidas por impresora |
| `GET /jobs/{id}` | `queued` → `submitted` / `failed` |

Todos (salvo `/health`) requieren header `X-API-Key`. Pág. 1 del PDF = frente, pág. 2 = reverso.
Estado `submitted` = aceptado por CUPS, no "carnet impreso" (ver pendientes).

## UI (generador de carnets)

`web/generador-carnets.html` se sirve en `http://localhost:8080/ui/generador-carnets.html`. Las impresoras
“vía middleware (API)” rasterizan frente/reverso en el navegador (1011×638 px) y las envían a `POST /jobs`.
La URL y la API key se guardan en `localStorage` (panel “Conexión al middleware”).

## Estado de verificación

- **Zebra ZC300 (verificado, macOS):** driver Mac 1.0.10.0 de Zebra instalado, cola CUPS `Zebra_ZC300`
  por USB, tarjeta de prueba de 2 páginas impresa vía `POST /jobs`, y tarjeta real impresa desde el generador
  (`/ui/generador-carnets.html`, impresora “ZC300 vía API”). Opciones tomadas del PPD oficial
  (ver `printers.example.yaml`). El driver Linux de Zebra (DZCG.1.0.0.0, 2018) **no** está probado.
- **Entrust Sigma DS3 (sin verificar):** hay driver Linux "LXM" (CUPS) según Entrust, pero no se pudo
  descargar ni probar; el driver XPS es solo Windows. Falta conectar la impresora y obtener el driver.
- **Overlay con bitmap / paneles de seguridad:** se configuran en la app de Zebra, no por opciones CUPS;
  por CUPS solo se elige `RibbonName`/`RibbonCombination` (p. ej. `15Hologram`). Probar con la cinta puesta.

## CarnetPrint.exe (Windows, Entrust Sigma DS3)

`build-exe.ps1` genera `dist\CarnetPrint.exe` + `dist\bridge\` (CardBridge.exe y sus DLL). Copiar ambos
juntos al equipo con el driver XPS de Entrust y el .NET 8 Runtime; doble clic y se abre el generador.

Junto al .exe, en la primera ejecución, se crean solos:

| Archivo | Contenido |
|---|---|
| `.env` | API key aleatoria (también se imprime en consola) |
| `printers.yaml` | Impresora Entrust (editar `printer_name` si hace falta) |
| `templates.json` | Plantillas y cuál es la activa para el API |
| `carnets.json` | Carnets generados (registro, reimpresiones, anulados) |
| `settings.json` | Ajustes de «Avanzado»: impresora, calidad, tolva y calibración X/Y por impresora |
| `clients.json` | Perfiles de cliente (modo kiosko) |
| `png\` | Una carpeta por trabajo (`AAAAMMDD-HHMMSS_<control>`) con `front.png`, `back.png` y las capas K |

API (todos con `X-API-Key`): imprime **directo**, sin PDF.
- `POST /jobs`: `front` + `back` (PNG), `front_k`/`back_k` opcionales, `template_id` opcional
  (si no viene se usa la plantilla activa).
- `GET /templates`, `PUT|GET|DELETE /templates/{id}`, `POST /templates/{id}/activate`.
- `GET /cards`, `PUT /cards/{control}`.

**Todo se imprime por el API** (PNG directo al SDK de la impresora); ya no hay impresión por el diálogo del
navegador. La tarjeta de calibración también sale por el API.

**Modo kiosko (por cliente):** en «Avanzado > Clientes» se crea un perfil (plantilla fija + campos que se pueden
llenar). `http://localhost:8787/c/<cliente>` (o `CarnetPrint.exe --client <cliente>`) abre el generador ya
configurado: sin diseño, sin ajustes, sin selector de plantilla; solo se llenan los campos permitidos. La API key
solo se incrusta en la página si se abre desde la misma PC.
`GET|PUT|DELETE /clients/{id}` administran los perfiles.

Los datos de un navegador que usaba IndexedDB se suben solos al .exe la primera vez que se abre la UI.

## Qué no está en el repo

- **Drivers e instaladores** (Entrust XPS 8.8, Zebra): se descargan desde los enlaces de `HANDOFF.md`; no se redistribuyen.
- **Binarios compilados** (`bridge/bin`, `bridge/zbin`, `obj/`): salen de `build-exe.ps1` o `bridge\build.ps1`.
- **Secretos**: `.env` no se versiona. El `.exe` lo crea con una API key aleatoria; en desarrollo, copia `.env.example` a `.env`.

## Pendientes / siguiente paso

- Probar cinta Hologram y cinta de seguridad con tarjeta real.
- Obtener y probar el driver del DS3.
- Si la webapp está en otro dominio: HTTPS delante (nginx/caddy) y `CARDPRINT_CORS_ORIGINS`.
- Servicio systemd: `deploy/cardprint.service`.
