/* Funciones puras del generador (sin DOM): se prueban con `node --test tests/js`. */
(function (root, factory) {
  const lib = factory();
  if (typeof module === "object" && module.exports) module.exports = lib;
  else root.CarnetLib = lib;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ESCAPES[c]);

  const digits = s => String(s || "").replace(/\D/g, "");

  /** 00112345678 -> 001-1234567-8 (formatea mientras se escribe). */
  function fmtCed(s) {
    const d = digits(s).slice(0, 11);
    if (d.length <= 3) return d;
    if (d.length <= 10) return d.slice(0, 3) + "-" + d.slice(3);
    return d.slice(0, 3) + "-" + d.slice(3, 10) + "-" + d.slice(10);
  }

  /** Dígito verificador de la cédula dominicana (Luhn con pesos 1,2). */
  function validCed(s) {
    const d = digits(s);
    if (d.length !== 11) return false;
    let sum = 0;
    for (let i = 0; i < 10; i++) {
      let p = parseInt(d[i], 10) * (i % 2 === 0 ? 1 : 2);
      if (p > 9) p -= 9;
      sum += p;
    }
    return (10 - (sum % 10)) % 10 === parseInt(d[10], 10);
  }

  const pad = n => String(n).padStart(2, "0");
  /** Fecha local como AAAA-MM-DD. (toISOString da la fecha UTC: de noche en América sale mañana.) */
  const isoDate = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const todayISO = (now = new Date()) => isoDate(now);

  /** Fecha de expiración: `issue` (AAAA-MM-DD) + n años o meses. Un 31 de enero + 1 mes = fin de febrero. */
  function addValidity(issue, n, unit) {
    const [y, m, d] = issue.split("-").map(Number);
    const months = unit === "years" ? n * 12 : n;
    const first = new Date(y, m - 1 + months, 1);
    const lastDay = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
    return isoDate(new Date(first.getFullYear(), first.getMonth(), Math.min(d, lastDay)));
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    const [y, m, d] = iso.split("-");
    return `${d}/${m}/${y}`;
  }

  /** «Colegio San José» -> «colegio-san-jose» (id de plantilla o cliente). */
  const slug = n =>
    String(n).trim().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48);

  /* ---------- Layout de la tarjeta (rótulos, tamaños, ajuste de texto, márgenes) ---------- */
  const CARD_W = 342.4;   // 85.6 mm a 4 px/mm
  const FIELD = { size: 12, bold: true, fit: "shrink", maxLines: 2, minSize: 8 };
  const DEFAULT_LAYOUT = Object.freeze({
    front: {
      margins: { top: 9, right: 12, bottom: 9, left: 12 },
      gap: 14,
      photo: { width: 88, height: 108 },
      fields: {
        name: { ...FIELD, label: "Nombre" },
        ced: { ...FIELD, label: "Cédula" },
        cat: { ...FIELD, label: "Categoría" },
        extra: { ...FIELD, label: "—" },
      },
      footer: {
        issue: { ...FIELD, label: "Emisión" },
        expiry: { ...FIELD, label: "Expiración" },
        code: { ...FIELD, label: "Código" },
      },
    },
    back: { margins: { top: 14, right: 14, bottom: 14, left: 14 } },
  });

  const isObject = v => v !== null && typeof v === "object" && !Array.isArray(v);

  /** Valores por defecto + lo que traiga `layout` (null/undefined no pisan nada). No modifica sus argumentos. */
  function mergeLayout(base, over) {
    if (!isObject(base)) return over === undefined || over === null ? base : over;
    const out = {};
    for (const key of new Set([...Object.keys(base), ...(isObject(over) ? Object.keys(over) : [])])) {
      out[key] = mergeLayout(base[key], isObject(over) ? over[key] : undefined);
    }
    return out;
  }
  const resolveLayout = layout => mergeLayout(DEFAULT_LAYOUT, layout || {});

  const getPath = (obj, path) => path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);

  /** Copia de `obj` con `value` en `path` («front.margins.top»). */
  function setPath(obj, path, value) {
    const [head, ...rest] = path.split(".");
    const child = rest.length ? setPath(isObject(obj?.[head]) ? obj[head] : {}, rest.join("."), value) : value;
    return { ...(obj || {}), [head]: child };
  }

  /** Ancho (px) que le queda al texto de los campos del frente, junto a la foto. */
  const fieldsWidth = front => CARD_W - front.margins.left - front.margins.right - front.photo.width - front.gap;

  /** Ancho (px) de cada una de las 3 columnas del pie (separación = FOOTER_GAP, la misma de app.css). */
  const FOOTER_GAP = 10;
  const footerWidth = front => (CARD_W - front.margins.left - front.margins.right - 2 * FOOTER_GAP) / 3;

  /** Parte `text` en líneas de a lo más `maxWidth` (por palabras). `measure(texto)` -> ancho. */
  function wrapLines(text, maxWidth, measure) {
    const lines = [];
    let line = "";
    for (const word of String(text).split(/\s+/).filter(Boolean)) {
      const attempt = line ? line + " " + word : word;
      if (line && measure(attempt) > maxWidth) { lines.push(line); line = word; }
      else line = attempt;
    }
    if (line) lines.push(line);
    return lines.length ? lines : [""];
  }

  /**
   * Tamaño de letra y líneas para que `text` quepa en `avail` px según la política del campo:
   * clip = tal cual (se corta con «…»), shrink = una línea con la letra más chica (hasta minSize),
   * wrap = hasta maxLines líneas, bajando la letra si aún no cabe. `measure(texto, size, bold)` -> ancho.
   */
  function fitField(text, field, avail, measure) {
    const width = avail * 0.97;   // un poco de holgura: el navegador mide distinto que el canvas
    const step = 0.5;
    let size = field.size;
    if (field.fit === "shrink") {
      while (size > field.minSize && measure(text, size, field.bold) > width) size -= step;
      return { size: Math.max(size, Math.min(field.minSize, field.size)), lines: 1 };
    }
    if (field.fit === "wrap") {
      const linesAt = s => wrapLines(text, width, t => measure(t, s, field.bold)).length;
      while (size > field.minSize && linesAt(size) > field.maxLines) size -= step;
      return { size: Math.max(size, Math.min(field.minSize, field.size)), lines: field.maxLines };
    }
    return { size, lines: 1 };
  }

  return {
    esc, digits, fmtCed, validCed, todayISO, isoDate, addValidity, fmtDate, slug,
    CARD_W, DEFAULT_LAYOUT, resolveLayout, getPath, setPath, fieldsWidth, footerWidth, wrapLines, fitField,
  };
});
