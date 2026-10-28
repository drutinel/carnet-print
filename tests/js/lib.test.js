const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("../../web/lib.js");

test("esc neutraliza HTML", () => {
  assert.equal(L.esc(`<img src=x onerror="a('b')">&`), "&lt;img src=x onerror=&quot;a(&#39;b&#39;)&quot;&gt;&amp;");
  assert.equal(L.esc(null), "");
  assert.equal(L.esc(0), "0");
});

test("fmtCed formatea mientras se escribe y recorta a 11 dígitos", () => {
  assert.equal(L.fmtCed("0011"), "001-1");
  assert.equal(L.fmtCed("00112345678"), "001-1234567-8");
  assert.equal(L.fmtCed("001-1234567-8999"), "001-1234567-8");
  assert.equal(L.fmtCed("abc"), "");
});

test("validCed acepta el dígito verificador correcto y rechaza el resto", () => {
  assert.equal(L.validCed("001-1234567-3"), true);
  assert.equal(L.validCed("00112345673"), true);
  assert.equal(L.validCed("001-1234567-8"), false);   // dígito verificador equivocado
  assert.equal(L.validCed("001-1234567"), false);
  assert.equal(L.validCed(""), false);
});

test("todayISO usa la fecha LOCAL (no la UTC)", () => {
  // 28/10 a las 21:30 en hora local: toISOString() en UTC-4 diría 29/10
  assert.equal(L.todayISO(new Date(2026, 9, 28, 21, 30)), "2026-10-28");
  assert.equal(L.todayISO(new Date(2026, 0, 1, 0, 5)), "2026-01-01");
});

test("addValidity suma años y meses sin correrse de día", () => {
  assert.equal(L.addValidity("2026-10-28", 1, "years"), "2027-10-28");
  assert.equal(L.addValidity("2026-10-28", 6, "months"), "2027-04-28");
  assert.equal(L.addValidity("2026-01-31", 1, "months"), "2026-02-28");   // fin de mes
  assert.equal(L.addValidity("2024-02-29", 1, "years"), "2025-02-28");    // bisiesto
  assert.equal(L.addValidity("2026-12-15", 3, "months"), "2027-03-15");
});

test("fmtDate", () => {
  assert.equal(L.fmtDate("2026-10-28"), "28/10/2026");
  assert.equal(L.fmtDate(""), "—");
});

test("slug quita tildes y símbolos", () => {
  assert.equal(L.slug("  Colegio San José #1 "), "colegio-san-jose-1");
  assert.equal(L.slug("¡¡¡"), "");
  assert.equal(L.slug("a".repeat(80)).length, 48);
});
