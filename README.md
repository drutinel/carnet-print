# CarnetPrint

Generador e impresor de carnets (CR80, frente y reverso) para la **Entrust Sigma DS3**. Un solo
`CarnetPrint.exe` levanta la web de captura, imprime **directo** por el SDK de Entrust (sin PDF y sin
diálogo de impresión) y guarda plantillas, carnets y PNG junto a sí mismo.

## Instalar

Descarga `CarnetPrint-Setup-<versión>.exe` de la [última release](https://github.com/drutinel/carnet-print/releases/latest)
y ejecútalo. En una sola pasada:

- copia el programa a `C:\CarnetPrint` (ahí se guardan también tus datos);
- instala el **.NET 8 Desktop Runtime** si falta (incluido, sin internet);
- ofrece descargar e instalar el **driver XPS de Entrust 8.8** si Windows no tiene la impresora `XPS Card Printer`;
- crea los accesos directos. Al desinstalar **no** borra tus datos.

Windows SmartScreen puede avisar de «editor desconocido» (los archivos no están firmados): *Más información > Ejecutar de todos modos*.

**A mano:** copia `CarnetPrint.exe` **y la carpeta `bridge\` juntas** (solo el `.exe` no basta). Requisitos:

| Requisito | Descarga |
|---|---|
| Driver XPS de Entrust 8.8 | [XPSCardPrinter_8.8.048.0.exe](https://downloads.entrust.com/drivers/XPSCardPrinter_8.8.048.0.exe) · [soporte DS3](https://www.entrust.com/support/instant-id-card-issuance-systems/ds3-direct-to-card-printer-support) |
| .NET 8 Desktop Runtime (x64) | [dotnet.microsoft.com/download/dotnet/8.0](https://dotnet.microsoft.com/download/dotnet/8.0) |
| La DS3 conectada por USB y encendida | — |

Si falta algo, el programa lo avisa **al abrir** (consola y aviso amarillo en la web) con el enlace de descarga.

## Usar

1. Abre **CarnetPrint** (el acceso directo, o `CarnetPrint.exe`). Se abre `http://localhost:8787/ui/generador-carnets.html`.
2. La primera vez se crean junto al `.exe` el `.env` (con una **API key aleatoria**) y `printers.yaml`. Si Windows llama
   distinto a la impresora, edita `printer_name` en `printers.yaml`.
3. Toca la tarjeta para escribir nombre, cédula y categoría; sube la foto; **Generar, registrar e imprimir**.
   El servidor asigna el número de control y el código.

La web abierta desde esa misma PC ya trae la clave; desde otra máquina te la pide (está en `.env`).

| Archivo junto al `.exe` | Contenido |
|---|---|
| `.env` | API key y opciones (`CARDPRINT_PORT`, `CARDPRINT_OPEN_BROWSER`…). No se comparte |
| `printers.yaml` | Impresoras y opciones permitidas por trabajo |
| `templates.json` | Plantillas de diseño y cuál usa el API por defecto |
| `carnets.json` | Carnets generados (registro, reimpresiones, anulados), sin imágenes |
| `settings.json` | Ajustes de **Avanzado**: impresora, calidad, tolva y calibración X/Y por impresora |
| `clients.json` | Perfiles de cliente (modo kiosko) y sus tokens |
| `draft.json` | El carnet que se estaba llenando (uno por administrador y por kiosko); sobrevive a cerrar el programa |
| `carnets/` | Un JSON por carnet emitido (`C-000001.json`), con la foto incluida: copia legible que se puede restaurar con «Restaurar respaldo» |
| `images/` | Logos, sellos, firmas y fotos (una vez cada imagen) |
| `png/` | Una carpeta por trabajo (`AAAAMMDD-HHMMSS_<control>`) con `front.png`, `back.png` y las capas K |

Para respaldar o mover el programa basta copiar la carpeta completa (con `images/`).

**Si se cierra o se reinicia el programa no se pierde lo que estabas llenando:** el borrador se guarda en el servidor y vuelve solo, aunque abras la web desde otro navegador o puerto. El botón **«Continuar desde el último»** carga los datos del último carnet emitido (el código y la fecha son nuevos). Las fotos se reducen a 800 px al subirlas, así que una foto de celular no supera el límite.

### Línea de comandos (impresión directa)

`CarnetPrint.exe` también se maneja sin la web, para scripts o reimpresiones. Imprime **PNG ya hechos** (los mismos
que el programa archiva en `png\`):

```powershell
# dos caras (y, si quieres, las capas negras)
CarnetPrint.exe print --front frente.png --back reverso.png [--front-k fk.png --back-k rk.png]
# reimprimir un trabajo archivado, o un carnet registrado con su último PNG
CarnetPrint.exe print --png-dir png\20261028-131500_C-000001
CarnetPrint.exe print --card C-000001
# otras opciones
CarnetPrint.exe print --card C-000001 --copies 2 --printer entrust-sigma-ds3 --json
CarnetPrint.exe printers --json        # impresoras y su estado
```

- Usa las mismas opciones que la web (calidad, tolva, split ribbon de **Avanzado**, en `settings.json`); con
  `--option CLAVE=VALOR` se usan solo las que indiques. Los desplazamientos X/Y ya van dentro de los PNG.
- Si el programa está abierto, el trabajo pasa por **su cola** (dos impresiones nunca se pisan); si no, imprime directo.
- `--card` cuenta una reimpresión solo si la tarjeta salió bien.
- `--json` da una sola línea parseable. **Códigos de salida:** `0` impreso, `1` falló o se agotó la espera, `2` petición inválida
  (archivo que no existe, opción no permitida…).
- Armar el carnet a partir de datos (nombre, cédula…) sigue siendo cosa de la web: la tarjeta se dibuja en el navegador.

### Layout de la tarjeta (rótulos, ajuste de texto y márgenes)

En **Diseño de la plantilla > Campos y márgenes de la tarjeta** se cambia, por plantilla: el rótulo de cada campo
(«Categoría» → «Rango»), su tamaño y negrita, **qué hacer si el texto no cabe** (cortar con «…», achicar la letra o
varias líneas), los márgenes del frente y del reverso, el tamaño de la foto y el espacio foto-texto. «Editar JSON» muestra
el mismo layout completo; el servidor lo valida (rangos y claves) antes de guardarlo. Cada carnet guarda el layout con el
que se hizo, así que reimprimirlo da la misma tarjeta aunque la plantilla cambie después.

```json
"layout": { "front": {
  "margins": { "top": 9, "right": 6, "bottom": 9, "left": 6 }, "gap": 8, "photo": { "width": 88, "height": 108 },
  "fields": { "cat": { "label": "Rango" }, "extra": { "label": "Cargo", "fit": "wrap", "maxLines": 2, "minSize": 9 } } } }
```

### Modo kiosko por cliente

En **Avanzado > Clientes** se crea un perfil: plantilla fija + campos que se pueden llenar. `http://localhost:8787/c/<cliente>`
(o `CarnetPrint.exe --client <cliente>`) abre el generador ya configurado, sin diseño, ajustes ni selector de plantilla.
Cada perfil tiene **su propio token**, que el servidor limita: solo imprime y registra con su plantilla, lee la
configuración y, si el perfil lo permite, el registro. No puede cambiar plantillas, ajustes ni perfiles, ni anular o
exportar. Eliminar el perfil revoca su token. Quien llegue a la URL del kiosko puede usarlo (es su propósito).

## API

`X-API-Key` con la API key (administrador) o con el token de un kiosko. Públicos: `/health` y `/preflight`.

| Método y ruta | Quién | Qué hace |
|---|---|---|
| `POST /jobs` | ambos | Imprime: `printer_id`, `front` y `back` (PNG), `front_k`/`back_k` opcionales, `template_id`, `control`, `copies`, `options` |
| `GET /jobs/{id}` | ambos | `queued` → `printed` / `failed` |
| `GET /printers`, `GET /printers/{id}/options` | ambos | Impresoras (`ready`, `busy`, `offline`, `unknown`; con caché) y opciones permitidas |
| `GET /templates`, `GET /templates/{id}` | ambos (el kiosko solo la suya) | Plantillas; la activa es la que usa el API |
| `PUT\|DELETE /templates/{id}`, `POST /templates/{id}/activate` | admin | Administrar plantillas |
| `POST /cards` | ambos | Alta: el servidor asigna `control` (`C-000001`…) y el código |
| `GET /cards/last` | ambos | El último carnet emitido por quien llama (el administrador ve el último de todos) |
| `GET\|PUT\|DELETE /draft` | ambos | El borrador del titular |
| `GET /cards`, `GET /cards/{control}` | admin, o kiosko con registro | Registro liviano / carnet completo con imágenes |
| `GET /cards?full=true`, `PUT /cards/{control}`, `POST /cards/{control}/void` | admin | Respaldo, restaurar, anular |
| `POST /cards/{control}/reprint` | admin, o kiosko con registro | Cuenta una reimpresión |
| `GET\|PUT /settings` | lee: ambos · escribe: admin | Ajustes de Avanzado |
| `GET\|PUT\|DELETE /clients/{id}` | admin | Perfiles de kiosko |
| `GET /preflight`, `GET /health` | público | Qué le falta a la PC (con enlaces); estado y versión |

Todo JSON de entrada se valida con límites de tamaño; las imágenes deben ser `data:image/(png|jpeg|webp|gif)` de hasta ~2 MB.
Detalle de diseño: [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## Desarrollo

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"   # en Windows: .venv\Scripts\pip
cp .env.example .env                                         # y pon tu propia API key
.venv/bin/python -m pytest                                   # Python
node --test tests/js/*.test.js                               # funciones puras de la web
.venv/bin/python -m app.server                               # http://localhost:8787
```

Compilar el `.exe` **solo se puede en Windows** (PyInstaller no compila para otro sistema):

```powershell
powershell -ExecutionPolicy Bypass -File build-exe.ps1   # necesita Python 3.11+ y .NET SDK 8
```

Genera `dist\CarnetPrint.exe` y `dist\bridge\`. El instalador (`installer\CarnetPrint.iss`, Inno Setup 6.1+) se compila
en el workflow.

### GitHub Actions

`.github/workflows/build-exe.yml` corre en un Windows de GitHub: tests de Python y de la web, compila el puente y el
`.exe`, **arranca el `.exe` y comprueba que sirve la web**, arma el instalador y lo prueba en silencio.

- **Push a `main`:** publica un Release con versión `vX.Y.<n° de ejecución>` (`X.Y` salen de `version` en `pyproject.toml`).
  `[skip release]` en el mensaje del commit compila y prueba sin publicar. Los cambios solo de documentación no disparan nada.
  Se conservan los **10 releases más recientes**; los anteriores se borran junto con su etiqueta.
- **Etiqueta `v*`:** publica un Release con ese nombre exacto.
- **Pull request / manual:** compila y prueba; el resultado queda como artefacto 30 días.

Las acciones están fijadas por SHA y Dependabot propone las actualizaciones. Los minutos los paga el dueño del repo
(gratis si es público).

## Qué no está en el repo

Instaladores y drivers (se bajan de los enlaces de arriba), binarios compilados, `.env`, entornos virtuales y los
datos que el programa genera. El `.exe` crea su propio `.env` y `printers.yaml`.

## Estado y pendientes

- **Verificado con la DS3 real:** impresión frente/reverso con el puente de Entrust (versión de desarrollo en Windows).
- **No verificado:** el instalador y el aviso de requisitos en una PC limpia; la impresión con los builds publicados.
- Probar cinta Hologram y de seguridad con tarjeta real.
- Los archivos no están firmados (SmartScreen avisa); firmarlos requiere un certificado de firma de código.
- Zebra ZC300: conservada pero sin verificar con la impresora → [docs/ZEBRA.md](docs/ZEBRA.md).

## Documentación de Entrust

[Guía del driver XPS 8.8](https://www.entrust.com/sites/default/files/documentation/productsupport/527280-005l-xps-card-printer-driver-8-8.pdf) ·
[SDK Reference Guide](https://www.entrust.com/sites/default/files/documentation/productsupport/527250-003h-reference-guide-windows-xps-driver-software-development-kit-sdk.pdf) ·
[Guía de instalación DS1/DS2/DS3](https://www.entrust.com/sites/default/files/documentation/productsupport/528062-001l-ds1-ds2-ds3-inst-admin-guide.pdf) ·
[XPS Driver SDK v8.8 (zip)](https://downloads.entrust.com/drivers/XPS_Card_Printer_SDK_v8.8.zip)
