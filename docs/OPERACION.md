# Operación: línea de comandos, edición de carnets y manejo del repositorio

Guía para quien usa y mantiene CarnetPrint. Para instalar y para el API, ver el [README](../README.md); para el diseño
interno, [ARQUITECTURA.md](ARQUITECTURA.md).

## 1. Línea de comandos (impresión directa)

`CarnetPrint.exe` se maneja también sin la web, para scripts o reimpresiones. Imprime **PNG ya hechos**: los mismos que el
programa archiva en `png\` en cada trabajo.

```powershell
# Dos caras (y, si quieres, las capas negras de 1 bit, del mismo tamaño que su cara)
CarnetPrint.exe print --front frente.png --back reverso.png [--front-k fk.png --back-k rk.png]

# Reimprimir un trabajo archivado, o un carnet registrado con su último PNG archivado
CarnetPrint.exe print --png-dir png\20261028-131500_C-000001
CarnetPrint.exe print --card C-000001

# Más opciones
CarnetPrint.exe print --card C-000001 --copies 2 --printer entrust-sigma-ds3 --json
CarnetPrint.exe printers --json          # impresoras y su estado
CarnetPrint.exe --version
```

| Opción | Qué hace |
|---|---|
| `--front`, `--back` | PNG de cada cara (van juntos). `--front-k` / `--back-k`: capa negra (panel K) |
| `--png-dir DIR` | Carpeta de un trabajo archivado (`front.png`, `back.png`, y las capas K si existen) |
| `--card C-000001` | Reimprime ese carnet con su PNG archivado más reciente en `png\`. La reimpresión **solo se cuenta si la tarjeta salió bien** |
| `--printer ID` | Impresora (por omisión, la elegida en Avanzado o la única) |
| `--copies N` | 1 a 10 |
| `--option CLAVE=VALOR` | Opción de la impresora (repetible). Con ella se usan **solo** las indicadas, no las de Avanzado |
| `--template ID`, `--control C-…` | Plantilla con la que se hizo; número de control con el que se nombra la carpeta de PNG |
| `--timeout S` | Segundos máximos de espera (por omisión 480) |
| `--json` / `--quiet` | Resultado en una sola línea JSON / sin avances en pantalla |

**Cómo decide dónde imprimir:** si CarnetPrint está abierto, el trabajo pasa por **su cola** (dos impresiones nunca se pisan);
si no, imprime directo con el mismo código del API. Las opciones (calidad, tolva, split ribbon) salen de `settings.json`,
igual que en la web. Los desplazamientos X/Y de calibración ya van dentro de los PNG.

**Códigos de salida:** `0` impreso · `1` falló o se agotó la espera · `2` petición inválida (archivo inexistente, opción no
permitida, copias fuera de rango…). Con `--json`, la salida es:

```json
{"ok": true, "state": "printed", "printer": "entrust-sigma-ds3", "printerLabel": "Entrust Sigma DS3", "copies": 1,
 "control": "C-000001", "job": "entrust:7", "pngDir": "20261028-171506_C-000001", "error": null, "via": "directo"}
```

**Qué no hace:** armar el carnet a partir de nombre y cédula. La tarjeta se dibuja en el navegador (diseño, ajuste de texto,
foto), así que por línea de comandos se imprime lo ya dibujado. Si más adelante se necesita, haría falta un renderizador
aparte en el servidor.

## 2. Editar un carnet ya emitido

En el **registro**, un clic en un carnet lo carga en pantalla (con el diseño con el que se emitió):

1. Aparece el aviso azul «Estás corrigiendo el carnet C-000012» y el botón principal pasa a **«Guardar cambios e imprimir»**.
2. Corrige lo que haga falta (nombre, cédula, categoría, dato extra, foto, fecha) y pulsa el botón. Se guarda **en ese mismo
   carnet**: el control y el código no cambian, se cuenta una reimpresión y la versión anterior queda en su historial.
3. **«Emitir como carnet nuevo»** guarda esos datos como otro carnet, con control y código nuevos.
4. **«Cancelar»** no cambia nada y devuelve lo que estabas llenando antes (el borrador no se pisa).

Reglas: un carnet **anulado** no se edita (emite uno nuevo); un kiosko solo edita si su perfil muestra el registro y siempre
con su plantilla. El historial de correcciones (`revisions`, hasta 20) y quién y cuándo lo cambió (`updatedBy`, `updatedAt`)
viven en `carnets.json` y en `carnets\C-000012.json`.

API: `PATCH /cards/{control}` (cuerpo igual al de `POST /cards`); `409` si está anulado.

## 3. Qué se guarda y dónde

Todo queda junto al `.exe` (`C:\CarnetPrint` con el instalador). Para respaldar o mover el programa basta copiar la carpeta.

| Archivo o carpeta | Contenido |
|---|---|
| `carnets.json`, `carnets\` | Registro de carnets; además, **un JSON por carnet** con la foto incluida (restaurable con «Restaurar respaldo») |
| `draft.json` | Lo que se está llenando (uno por administrador y por kiosko): sobrevive a cerrar el programa o cambiar de navegador |
| `images\`, `png\` | Imágenes por hash (se guardan una sola vez) y las caras mandadas a imprimir, una carpeta por trabajo |
| `templates.json`, `settings.json`, `clients.json`, `.env`, `printers.yaml` | Plantillas (con su layout), ajustes de Avanzado, perfiles de kiosko, API key y impresoras |

## 4. Higiene del repositorio (el repo es público)

**Nunca deben subir:** firmas, fotos de personas, SVG, instaladores de terceros, `.env`, datos del programa. El `.gitignore`
lo impide: ignora `*.svg`, `firma*`, `foto-*`, `.env`, los datos del programa (`templates.json`, `carnets.json`, `settings.json`,
`clients.json`, `draft.json`, `carnets\`, `images\`, `png\`), `windows-drivers\`, `bin\`, `obj\`, `dist\`… Al hacer commit, **agrega archivos por nombre** (`git add ruta`), no con `git add -A`: así un archivo suelto en la
carpeta no se cuela. Revisa `git status` antes de cada commit.

### Si algo sensible llega a subirse

1. **Rotar** lo que sea rotable (API key, tokens). Quitar el archivo en un commit nuevo **no basta**: sigue en el historial.
2. **Respaldar** el repo antes de reescribir (`git bundle create ../respaldo.bundle --all`; contiene lo sensible: no lo subas).
3. **Reescribir el historial** con `git filter-repo` (hay que tenerlo instalado):

   ```bash
   git filter-repo --force --invert-paths --path-glob '*.svg'      # o --path ruta/exacta ...
   git remote add origin <url>        # filter-repo quita el remoto
   ```

4. Antes de subir, **borrar los releases y etiquetas** cuyo historial incluye lo sensible (`gh release delete vX --cleanup-tag`)
   y cerrar las ramas o PR basados en el historial viejo; si no, siguen apuntando a él.
5. **Force-push** con candado: `git push --force-with-lease=main:<sha-actual-del-remoto> origin main`
   (`git ls-remote origin refs/heads/main` da ese sha). Quien tenga clones debe volver a clonar.
6. **Verificar:** que el árbol remoto no lo contenga (`gh api "repos/<owner>/<repo>/git/trees/main?recursive=1"`), que ningún
   commit del historial lo tenga (`git log --all --name-only`) y que ninguna etiqueta, rama ni PR lo alcance.
7. **Pedir a GitHub Support** la eliminación de datos sensibles. Los commits viejos **siguen accesibles por su hash** hasta que
   GitHub los limpie, y los forks y clones existentes los conservan: solo ellos pueden purgarlos del servidor.

### Lo ocurrido con `firma.svg` (octubre de 2026)

Un commit con `git add -A` subió por accidente un archivo `firma.svg` ajeno al proyecto. Se reescribió el historial para quitar
todos los `*.svg`, se borraron el release y la etiqueta afectados y se reforzó el `.gitignore`. Queda pendiente la solicitud a
GitHub Support para purgar el commit viejo del servidor.
