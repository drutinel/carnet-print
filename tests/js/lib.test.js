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

// --- layout de la tarjeta ---
const fake = (text, size, bold) => String(text).length * size * 0.5;   // cada letra mide la mitad del tamaño

test("resolveLayout: sin layout son los valores de siempre", () => {
  const L2 = L.resolveLayout(null);
  assert.equal(L2.front.fields.cat.label, "Categoría");
  assert.equal(L2.front.margins.left, 12);
  assert.equal(L2.front.photo.width, 88);
  assert.equal(L2.back.margins.top, 14);
});

test("resolveLayout: mezcla solo lo que viene y no modifica nada", () => {
  const mine = { front: { fields: { cat: { label: "Rango", fit: "shrink" } }, margins: { left: 4 } }, back: null };
  const copy = JSON.parse(JSON.stringify(mine));
  const r = L.resolveLayout(mine);
  assert.equal(r.front.fields.cat.label, "Rango");
  assert.equal(r.front.fields.cat.size, 12);          // lo no indicado queda por defecto
  assert.equal(r.front.margins.left, 4);
  assert.equal(r.front.margins.right, 12);
  assert.equal(r.back.margins.top, 14);
  assert.deepEqual(mine, copy);                       // el argumento no cambió
  assert.equal(L.DEFAULT_LAYOUT.front.fields.cat.label, "Categoría");   // ni los valores por defecto
});

test("getPath / setPath son inmutables", () => {
  const a = { front: { margins: { top: 9 } } };
  const b = L.setPath(a, "front.margins.top", 3);
  assert.equal(a.front.margins.top, 9);
  assert.equal(L.getPath(b, "front.margins.top"), 3);
  assert.equal(L.getPath(L.setPath({}, "a.b.c", 1), "a.b.c"), 1);
  assert.equal(L.getPath(a, "front.nada.x"), undefined);
});

test("fieldsWidth: lo que queda junto a la foto", () => {
  const f = L.resolveLayout({}).front;
  assert.ok(Math.abs(L.fieldsWidth(f) - (342.4 - 12 - 12 - 88 - 10)) < 1e-9);
  assert.ok(L.fieldsWidth({ ...f, margins: { ...f.margins, left: 4, right: 4 } }) > L.fieldsWidth(f));   // menos margen, más ancho
});

test("wrapLines parte por palabras", () => {
  const m = t => t.length * 6;
  assert.deepEqual(L.wrapLines("DIRECTOR CENTRAL DE INTELIGENCIA", 100, m), ["DIRECTOR CENTRAL", "DE INTELIGENCIA"]);
  assert.deepEqual(L.wrapLines("DIRECTOR CENTRAL DE INTELIGENCIA", 60, m), ["DIRECTOR", "CENTRAL DE", "INTELIGENCIA"]);
  assert.deepEqual(L.wrapLines("", 100, m), [""]);
  assert.deepEqual(L.wrapLines("PALABRAMUYLARGUISIMA", 50, m), ["PALABRAMUYLARGUISIMA"]);   // no se parte una palabra
});

test("fitField clip no cambia nada", () => {
  const f = { size: 12, bold: true, fit: "clip", maxLines: 2, minSize: 8 };
  assert.deepEqual(L.fitField("DIRECTOR CENTRAL DE INTELIGENCIA", f, 100, fake), { size: 12, lines: 1 });
});

test("fitField shrink baja la letra hasta que cabe, sin pasar de minSize", () => {
  const f = { size: 12, bold: true, fit: "shrink", maxLines: 2, minSize: 8 };
  const r = L.fitField("DIRECTOR CENTRAL", f, 80, fake);           // 16 letras: a 12 px miden 96, no caben en 80
  assert.ok(r.size < 12 && r.size >= 8 && r.lines === 1);
  assert.ok(fake("DIRECTOR CENTRAL", r.size) <= 80 * 0.97);
  assert.equal(L.fitField("X".repeat(200), f, 100, fake).size, 8);   // no baja de minSize
  assert.equal(L.fitField("CORTO", f, 100, fake).size, 12);          // si cabe, no toca nada
});

test("fitField wrap usa varias líneas y baja la letra solo si hace falta", () => {
  const f = { size: 12, bold: true, fit: "wrap", maxLines: 2, minSize: 8 };
  const r = L.fitField("DIRECTOR CENTRAL DE INTELIGENCIA", f, 130, fake);
  assert.equal(r.lines, 2);
  assert.equal(r.size, 12);   // en 2 líneas cabe sin achicar
  const small = L.fitField("DIRECTOR CENTRAL DE INTELIGENCIA MILITAR NACIONAL", f, 100, fake);
  assert.ok(small.size < 12 && small.size >= 8);
});
