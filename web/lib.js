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

  return { esc, digits, fmtCed, validCed, todayISO, isoDate, addValidity, fmtDate, slug };
});
