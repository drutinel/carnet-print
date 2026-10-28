# Arquitectura

```
navegador (web/) ──HTTP──▶ FastAPI (app/) ──cola serial por impresora──▶ CardBridge.exe ──▶ driver XPS ──▶ DS3
      │                        │
      │ PNG por cara           ├─ templates.json · carnets.json · settings.json · clients.json
      └ rasteriza en el        ├─ images/ (imágenes por hash)  ·  png/ (lo que se mandó a imprimir)
        navegador              └─ printers.yaml · .env
```

Todo corre en la misma PC, junto a `CarnetPrint.exe`. El navegador dibuja el carnet y lo rasteriza a PNG a
1015×640 px (300 ppp, tamaño nativo del driver); el servidor valida, archiva y manda los PNG al puente.

## Módulos (`app/`)

| Módulo | Responsabilidad |
|---|---|
| `server.py`, `run_exe.py` | Punto de entrada del `.exe`: crea la config, comprueba requisitos, levanta el API |
| `main.py` | `create_app()`: arma el contexto y monta los routers |
| `routes/` | Un router por tema (`jobs`, `cards`, `templates`, `clients`, `settings`, `printers`, `pages`, `system`). Delgados: validan y delegan |
| `schemas.py` | Esquemas pydantic de toda entrada JSON, con límites de tamaño |
| `deps.py` | Autenticación: `Principal` (administrador con la API key, o kiosko con su token) y los permisos `require_*` |
| `store.py` | Los cuatro JSON (escritura atómica con lock) y `images/` (imágenes por hash). Asigna controles |
| `jobs.py` | Cola serial por impresora; recuerda los últimos 500 trabajos |
| `status.py` | Estado de la impresora con caché: no lanza el puente si hay un trabajo en curso ni más de una vez cada 20 s |
| `preflight.py` | Requisitos de la PC (.NET, `CardBridge.exe`, impresora de Windows) con enlaces de descarga |
| `printers/` | Adaptadores: `entrust-sdk` y `zebra-sdk` (puente por línea de comandos) y `mock` (tests) |
| `render.py` | Valida y normaliza los PNG (RGB sin alfa; capas K a 1 bit del mismo tamaño) |

## Decisiones

- **Sin PDF ni diálogo de impresión:** los PNG van directo al SDK. El tamaño de página y la escala ya no dependen del navegador.
- **El servidor asigna el control** (`C-000001`…) dentro del lock del archivo: dos kioskos a la vez no se pisan.
- **Imágenes aparte:** un logo que usan mil carnets se guarda una vez; `carnets.json` y `templates.json` quedan livianos
  y el registro (`GET /cards`) no lleva imágenes. Los JSON viejos con imágenes dentro se compactan al arrancar.
- **Kiosko con token propio:** el servidor, no la web, hace cumplir lo que puede hacer (ver README). La API key solo se
  incrusta en la página del administrador si el navegador está en la misma PC (peer loopback y `Host` local, contra DNS rebinding).
- **Entradas validadas:** nada se guarda sin pasar por un esquema con límites (texto, imágenes, número de plantillas y clientes).
- **Si no se puede archivar el PNG, no se imprime.**

## Puente de Entrust (`bridge/CardBridge`)

Programa .NET 8 (WPF/WinForms) que usa los fuentes del *XPS Card Printer SDK v8.8* (`bridge/CardBridge/EntrustSdk/`, COM
`IBidiSpl`): `BindDevice` → estado → `StartJob` → `PrintDocument` + Print Ticket → `EndJob` → sondeo hasta `JobSucceeded`.
El trabajo pasa a `printed` solo cuando la impresora confirma que la tarjeta salió; los errores del equipo (sin tarjetas,
cinta, atasco) cancelan el trabajo y quedan en `error` con una instrucción para el operador (`app/printers/errors.py`).

- Opciones por trabajo vía Print Ticket: giro por cara, topcoat, desactivar una cara, tolva, calidad (`print_mode`,
  `color_dpi`, `mono_dpi`), split ribbon.
- DS3 de desarrollo: Sigma DS3IDRD, 300 ppp, cinta YMCKT, dúplex automático, sin banda magnética ni laminador.
- Convención del puente: `status` y `print --front F --back B …`; una línea JSON en stdout con `ok` y `printerJobId`.
- `Commit()` del Print Ticket cambia las preferencias del driver en esa PC; el SDK está pensado para eso.
- El SDK no trae un ensamblado: son fuentes C# (con copyright de Datacard/Entrust), copiadas sin modificar.

## Empaquetado

`build-exe.ps1` → `dist\CarnetPrint.exe` (PyInstaller, un solo archivo con la web dentro) + `dist\bridge\`.
`installer/CarnetPrint.iss` (Inno Setup) los junta con el .NET Desktop Runtime y la opción del driver de Entrust.
El workflow de GitHub Actions hace todo y publica el release; ver el README.
