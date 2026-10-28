# CarnetPrint

Generador e impresor de carnets (CR80, frente y reverso) para la **Entrust Sigma DS3**. Un solo
`CarnetPrint.exe` levanta la web de captura, imprime **directo** por el SDK de Entrust (sin PDF y sin
diálogo de impresión) y guarda plantillas, carnets generados y PNG junto a sí mismo.

## Qué necesita la PC

| Requisito | Para qué | Descarga |
|---|---|---|
| Windows 10/11 x64 | Todo | — |
| **Driver XPS de Entrust 8.8** | Es la impresora que ve Windows (`XPS Card Printer`); el SDK va encima | [XPSCardPrinter_8.8.048.0.exe](https://downloads.entrust.com/drivers/XPSCardPrinter_8.8.048.0.exe) · [página de soporte DS3](https://www.entrust.com/support/instant-id-card-issuance-systems/ds3-direct-to-card-printer-support) |
| **.NET 8 Desktop Runtime (x64)** | Lo usa `bridge\CardBridge.exe` | [dotnet.microsoft.com/download/dotnet/8.0](https://dotnet.microsoft.com/download/dotnet/8.0) |
| La DS3 conectada por USB y encendida | — | — |

Si falta algo, `CarnetPrint.exe` lo avisa al abrir: en la consola y en un aviso amarillo arriba de la página,
con el enlace de descarga y un botón «Volver a comprobar». No descarga ni instala nada por su cuenta.

> Los instaladores **no están en este repo** (licencia de terceros): se bajan de los enlaces de arriba.

## Uso

**Instalador (recomendado):** ejecuta `CarnetPrint-Setup-<versión>.exe` de la [última release](https://github.com/drutinel/carnet-print/releases/latest). Copia el programa a `C:\CarnetPrint`, instala el .NET 8 Desktop Runtime si falta (incluido, sin internet) y ofrece instalar el driver XPS de Entrust. No borra tus datos al desinstalar.

**A mano:** copia `CarnetPrint.exe` **y la carpeta `bridge\` juntos** a una carpeta de la PC (solo el `.exe` no basta: avisará que falta `CardBridge.exe`).

1. Doble clic. Se abre el navegador en `http://localhost:8787/ui/generador-carnets.html`.
3. La primera vez se crean, junto al `.exe`, `.env` (con una **API key aleatoria**, también impresa en consola)
   y `printers.yaml` (con la DS3). Si la Windows llama distinto a la impresora, edita `printer_name`.
4. Toca la tarjeta para escribir nombre, cédula y categoría; sube la foto; **Generar, registrar e imprimir**.

Todo lo que el programa guarda queda junto al `.exe`:

| Archivo | Contenido |
|---|---|
| `.env` | API key y opciones (`CARDPRINT_PORT`, `CARDPRINT_OPEN_BROWSER`…). No se comparte |
| `printers.yaml` | Impresoras y opciones permitidas por trabajo |
| `templates.json` | Plantillas de diseño y cuál usa el API por defecto |
| `carnets.json` | Carnets generados (registro, reimpresiones, anulados) |
| `settings.json` | Ajustes de **Avanzado**: impresora, calidad, tolva y calibración X/Y por impresora |
| `clients.json` | Perfiles de cliente (modo kiosko) |
| `png\` | Una carpeta por trabajo (`AAAAMMDD-HHMMSS_<control>`) con `front.png`, `back.png` y las capas K |

Para respaldar o mover el programa basta copiar la carpeta completa.

## Modo kiosko por cliente

En **Avanzado > Clientes** se crea un perfil: plantilla fija + campos que se pueden llenar. El enlace
`http://localhost:8787/c/<cliente>` (o `CarnetPrint.exe --client <cliente>`) abre el generador ya configurado, sin
diseño, ajustes ni selector de plantilla. La API key solo se incrusta en la página si se abre desde la misma PC.
El bloqueo es de interfaz: quien tenga la API key puede llamar al API directamente.

## API

Todo requiere el header `X-API-Key`, salvo `/health` y `/preflight`.

| Método y ruta | Qué hace |
|---|---|
| `POST /jobs` | Imprime: `printer_id`, `front` y `back` (PNG), `front_k`/`back_k` opcionales, `template_id`, `control`, `copies`, `options` |
| `GET /jobs/{id}` | Estado: `queued` → `printed` / `failed` |
| `GET /printers`, `GET /printers/{id}/options` | Impresoras y opciones permitidas |
| `GET /preflight` | Qué le falta a la PC (con enlaces); público |
| `GET\|PUT\|DELETE /templates/{id}`, `POST /templates/{id}/activate` | Plantillas; la activa es la que usa el API |
| `GET /cards`, `PUT /cards/{control}` | Carnets generados |
| `GET\|PUT /settings` | Ajustes de Avanzado |
| `GET\|PUT\|DELETE /clients/{id}` | Perfiles de cliente |

## Desarrollo

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"   # en Windows: .venv\Scripts\pip
cp .env.example .env                                         # y pon tu propia API key
.venv/bin/python -m pytest
.venv/bin/python -m app.server                               # http://localhost:8787
```

Compilar el `.exe` **solo se puede en Windows** (PyInstaller no compila para otro sistema):

```powershell
powershell -ExecutionPolicy Bypass -File build-exe.ps1   # necesita Python 3.11+ y .NET SDK 8
```

Genera `dist\CarnetPrint.exe` y `dist\bridge\`. El instalador (`installer\CarnetPrint.iss`, Inno Setup 6.1+) se compila en el workflow, que además descarga el .NET Desktop Runtime y verifica su firma de Microsoft.

### Compilar con GitHub Actions (sin PC Windows)

`.github/workflows/build-exe.yml` corre en un Windows de GitHub: pasa los tests, compila el puente y el `.exe`,
**arranca el `.exe` y comprueba que sirve la web y crea sus archivos**, y sube el resultado.

- **Push a `main`:** compila, prueba y **publica un Release solo**, con versión `vX.Y.<n° de ejecución>` (`X.Y` salen de
  `version` en `pyproject.toml`; sube ese número cuando quieras cambiar de serie). Si el mensaje del commit lleva
  `[skip release]`, compila y prueba sin publicar. Los cambios solo de documentación no disparan nada.
- **Etiqueta:** `git tag v1.0.0 && git push origin v1.0.0` publica un Release con ese nombre exacto.
- **Pull requests a `main`:** compilan y prueban, sin publicar.
- **Manual:** *Actions > Build CarnetPrint.exe > Run workflow*; el zip y el `.exe` quedan como artefactos 30 días.

Cada Release trae `CarnetPrint-Setup-<versión>.exe` (instalador), `CarnetPrint-<versión>-win-x64.zip` (`CarnetPrint.exe` + `bridge\`), el `.exe` suelto y las notas de
`.github/release-notes.md` con los requisitos de la PC.

Los minutos los paga el dueño del repo (gratis si es público). El build no prueba la impresión: eso requiere la DS3
y el driver XPS en la PC.

## Documentación

- Entrust: [guía del driver XPS 8.8](https://www.entrust.com/sites/default/files/documentation/productsupport/527280-005l-xps-card-printer-driver-8-8.pdf) ·
  [SDK Reference Guide](https://www.entrust.com/sites/default/files/documentation/productsupport/527250-003h-reference-guide-windows-xps-driver-software-development-kit-sdk.pdf) ·
  [guía de instalación DS1/DS2/DS3](https://www.entrust.com/sites/default/files/documentation/productsupport/528062-001l-ds1-ds2-ds3-inst-admin-guide.pdf) ·
  [XPS Driver SDK v8.8 (zip)](https://downloads.entrust.com/drivers/XPS_Card_Printer_SDK_v8.8.zip)
- Arquitectura: [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) · Notas de Windows: [WINDOWS.md](WINDOWS.md) · Estado y pendientes: [HANDOFF.md](HANDOFF.md)
- Zebra ZC300 y CUPS (ya fuera de este flujo): [docs/LEGADO-CUPS-ZEBRA.md](docs/LEGADO-CUPS-ZEBRA.md)

## Qué no está en el repo

Instaladores y drivers, binarios compilados (`bridge\bin`, `obj\`), `.env`, entornos virtuales y los datos que el
programa genera (`*.json`, `png\`). Los binarios salen de `build-exe.ps1`.
