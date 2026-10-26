# CarnetPrintService — arquitectura y estado real

Este documento es para quien vaya a instalar o a seguir desarrollando el
middleware, no para el operador que solo hace carnets. Léelo antes de
conectar una impresora de verdad.

## Qué resuelve

El generador (`web/generador-carnets.html`) es un archivo HTML suelto. Hasta
ahora imprimía abriendo el diálogo del navegador, lo que significa que el
tamaño de página, los márgenes y la escala dependían de que el operador los
dejara exactamente en "CR80 / Ninguno / 100 %" cada vez — y de que Chrome
redondeara los milímetros igual todos los días.

`CarnetPrintService` es un servicio pequeño que corre en la misma PC,
escucha solo en `127.0.0.1:17580` y recibe las dos imágenes del carnet ya
rasterizadas. Él fija el tamaño de página en centésimas de pulgada exactas y
dibuja en coordenadas absolutas, así que el navegador deja de intervenir en
la medida. Esa es la mejora real y ya funciona.

Todo lo que necesita el SDK propio de cada fabricante — banda magnética,
topcoat, panel UV, estado del equipo — queda detrás de una interfaz
(`IPrinterDriver`) y, mientras no esté verificado contra el equipo real,
el servicio sigue imprimiendo por el spooler de Windows en vez de fallar.

## Las tres piezas

```
generador-carnets.html  →  http://127.0.0.1:17580  →  CarnetPrintService
   (en el navegador)           (solo local)           (servicio de Windows)
                                                              │
                                                    ┌─────────┴─────────┐
                                                    │                   │
                                              EntrustXpsDriver    ZebraCardDriver
                                                    │                   │
                                              (spooler ahora;     (spooler ahora;
                                               SDK cuando se        SDK cuando se
                                               verifique)           verifique)
```

- **`web/generador-carnets.html`** — sin cambios de fondo respecto a la
  versión anterior. Se le agregó la casilla "Imprimir por el servicio de
  impresión": si el servicio responde, rasteriza la tarjeta con
  `html2canvas` a 300 ppp exactos y la manda por `fetch`; si el servicio no
  responde o falla, cae sola al diálogo del navegador de siempre. Nunca deja
  al operador sin forma de imprimir.
- **`src/CarnetPrintService/`** — el servicio en C# / .NET 8. Expone
  `/health`, `/printers`, `/print` y `/jobs`.
- **`tools/mock-service.js`** — el mismo contrato HTTP en Node, para probar
  el generador sin instalar nada de Windows. Guarda los PNG recibidos en
  `tools/salida/` en vez de imprimir. Así se validó el flujo completo
  (ver más abajo).

## Lo que SÍ está verificado

- El contrato HTTP completo (`/health`, `/printers`, `/print`, `/jobs`),
  probado de punta a punta contra `mock-service.js`: el generador rasteriza
  el carnet, lo manda, el servicio simulado lo guarda, y el tamaño que llega
  es el esperado.
- La impresión por el spooler de Windows (`SpoolDriver`): tamaño de página
  CR80 en centésimas de pulgada exactas, márgenes en cero, dibujo en
  coordenadas absolutas con desplazamiento fino en mm. Esta es una técnica
  estándar de `System.Drawing.Printing` y no depende de ningún SDK — es lo
  que realmente imprime en la ENTRUST y en la ZC300 desde el primer día.
- La normalización de imagen (`CardRenderer`): cualquier PNG que llegue se
  centra y se recorta al lienzo exacto de 1012 × 638 px (CR80 a 300 ppp),
  nunca se deforma.
- El respaldo automático en el HTML: si el servicio no está corriendo, o
  falla a mitad de un trabajo, el generador avisa y usa el diálogo del
  navegador sin que el operador tenga que hacer nada.

## Lo que NO está verificado — y qué hace falta para verificarlo

Esto es exactamente lo que señalé en la investigación de los SDK: ninguno
de los dos fabricantes publica un ensamblado .NET que se pueda descargar y
probar sin tener el instalador completo del SDK y, en el caso de Entrust,
sin tener la impresora enfrente. El código para ambos está escrito contra
la documentación pública, con el ciclo de llamadas correcto, pero con los
cuerpos marcados `TODO(SDK)` donde hace falta el ensamblado real.

**Entrust (`Printing/EntrustXpsDriver.cs`)**
1. Instalar "XPS Card Printer Driver SDK v8.8" desde el soporte del DS3.
2. Abrir el ensamblado `dxp01sdk` con el Examinador de objetos de Visual
   Studio y confirmar los nombres de tipo y de método reales — el código
   asume `StartJob` / `EndJob` sobre `IBidiSpl` y el patrón Print Ticket que
   describe la guía de referencia (527250-003f), pero las firmas exactas se
   tienen que leer del ensamblado, no de la documentación en PDF.
3. Copiar las cadenas de escape (topcoat, banda magnética) de la sección de
   escapes de esa misma guía a `src/CarnetPrintService/escapes.json`.
   Mientras ese archivo tenga las cadenas vacías, el servicio **rechaza**
   los trabajos que pidan banda magnética o topcoat personalizado con un
   mensaje claro, en vez de imprimir mal.
4. Probar primero con la tapa abierta y sin cinta, para ver que la tarjeta
   se mueve donde se espera antes de gastar material.

**Zebra (`Printing/ZebraCardDriver.cs`)**
1. Hay dos candidatos sin resolver: el paquete NuGet
   `Zebra.Printer.Card.SDK` (2018, .NET Framework 4.7.1 — probablemente
   incompatible con .NET 8 sin recompilar el servicio) y el SDK Link-OS que
   la propia documentación de Zebra usa para el ZC300
   (`developer.zebra.com/content/zc300-link-os-sdk-encode-data`). Hay que
   instalar el que Zebra entregue para el ZC300 y ver cuál ensamblado trae.
2. Confirmar si ese SDK cubre gráficos de cara completa y dúplex, o solo
   banda magnética / tarjeta inteligente — la documentación pública no lo
   aclara.
3. Zebra Browser Print (la vía que habría evitado este servicio del todo)
   está documentado para impresoras de código de barras, no para la serie
   ZC; no se investigó más a fondo porque habría significado adivinar.

Hasta que los dos puntos anteriores se resuelvan, `/printers` reporta el
driver como disponible pero con un `reason` que explica que se está usando
el spooler, y cualquier trabajo con banda magnética simplemente falla con
un mensaje — nunca se manda a ciegas.

## Cómo seguir desde aquí

El código no se escribió para funcionar a la primera contra el hardware
real — eso habría significado inventar nombres de métodos de un SDK que no
tengo instalado, y un trabajo de impresión que "funciona" con una llamada
inventada es peor que uno que avisa que le falta algo. Se escribió para que:

- la mejora real (medida exacta, sin depender del navegador) funcione hoy
  mismo con el spooler, y
- el camino para añadir banda magnética / topcoat cuando se tenga el SDK
  en la mano sea mecánico: llenar los `TODO(SDK)` y las cadenas de
  `escapes.json`, sin tocar el resto del servicio.

Cuando se verifiquen los nombres reales del ensamblado (con Visual Studio y
la impresora conectada), lo normal es que cada `TODO(SDK)` se convierta en
dos o tres líneas de llamada directa — el resto del flujo (cola, contrato
HTTP, respaldo en el navegador) no debería cambiar.
