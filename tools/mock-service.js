#!/usr/bin/env node
/**
 * Servicio simulado del middleware de carnets.
 *
 * Responde el mismo contrato HTTP que CarnetPrintService, pero en vez de
 * imprimir guarda los PNG que recibe en ./salida/. Sirve para dos cosas:
 *
 *   1. Probar el generador sin tener el servicio real instalado.
 *   2. Ver exactamente qué imagen se está mandando a la impresora, en el
 *      tamaño en que se manda, antes de gastar una tarjeta.
 *
 * Uso:  node mock-service.js [puerto]
 */
const http = require("http");
const fs = require("fs");
const path = require("path");

const PORT = Number(process.argv[2] || 17580);
const OUT = path.join(process.cwd(), "salida");
const W = 1012, H = 638, DPI = 300;

fs.mkdirSync(OUT, { recursive: true });

const jobs = new Map();
let seq = 0;

const PRINTERS = [
  {
    id: "entrust", name: "ENTRUST · Sigma DS3", driver: "EntrustXpsDriver",
    windowsName: "ENTRUST", available: true,
    reason: "Servicio simulado: no imprime, guarda los PNG en ./salida/.",
    capabilities: { duplex: true, magstripe: true, topcoat: true, uvPanel: true, lamination: true }
  },
  {
    id: "zc300", name: "Zebra ZC300", driver: "ZebraCardDriver",
    windowsName: "ZC300", available: true,
    reason: "Servicio simulado. Equipo configurado sin volteador: el reverso va aparte.",
    capabilities: { duplex: false, magstripe: true, topcoat: false, uvPanel: false, lamination: false }
  }
];

const json = (res, code, body) => {
  const s = JSON.stringify(body);
  res.writeHead(code, {
    "content-type": "application/json; charset=utf-8",
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "*",
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "content-length": Buffer.byteLength(s)
  });
  res.end(s);
};

function savePng(dataUrl, name) {
  if (!dataUrl) return null;
  const b64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
  const buf = Buffer.from(b64, "base64");
  const file = path.join(OUT, name);
  fs.writeFileSync(file, buf);
  // leer ancho/alto del IHDR, para comprobar que llega a 300 ppp
  const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);
  return { file, bytes: buf.length, w, h };
}

const server = http.createServer((req, res) => {
  if (req.method === "OPTIONS") return json(res, 204, {});

  const url = new URL(req.url, "http://127.0.0.1");

  if (url.pathname === "/health")
    return json(res, 200, {
      ok: true, service: "CarnetPrintService (simulado)", version: "1.0.0-mock",
      cardWidthPx: W, cardHeightPx: H, dpi: DPI
    });

  if (url.pathname === "/printers")
    return json(res, 200, { printers: PRINTERS });

  if (url.pathname === "/jobs" && req.method === "GET")
    return json(res, 200, { jobs: [...jobs.values()].reverse().slice(0, 25) });

  if (url.pathname.startsWith("/jobs/") && req.method === "GET") {
    const st = jobs.get(url.pathname.slice(6));
    return st ? json(res, 200, st) : json(res, 404, { error: "no existe" });
  }

  if (url.pathname === "/print" && req.method === "POST") {
    let body = "";
    req.on("data", c => { body += c; if (body.length > 26e6) req.destroy(); });
    req.on("end", () => {
      let r;
      try { r = JSON.parse(body); }
      catch { return json(res, 400, { error: "JSON inválido" }); }

      if (!r.printerId) return json(res, 400, { error: "Falta printerId." });
      if (!r.front) return json(res, 400, { error: "Falta la imagen del frente." });

      const id = "J-mock-" + (++seq).toString().padStart(4, "0");
      const stamp = (r.control || id).replace(/[^\w.-]/g, "_");
      const f = savePng(r.front, `${stamp}-frente.png`);
      const b = savePng(r.back, `${stamp}-reverso.png`);

      const warn = [];
      if (f && (f.w !== W || f.h !== H))
        warn.push(`el frente llegó a ${f.w}x${f.h} px en vez de ${W}x${H}`);
      if (b && (b.w !== W || b.h !== H))
        warn.push(`el reverso llegó a ${b.w}x${b.h} px en vez de ${W}x${H}`);

      const st = {
        jobId: id, printerId: r.printerId, control: r.control || null,
        state: "Done",
        message: (warn.length ? "AVISO: " + warn.join("; ") + ". " : "") +
                 `Guardado en ${OUT}` + (b ? " (dos caras)" : " (una cara)"),
        createdAt: new Date().toISOString(), finishedAt: new Date().toISOString()
      };
      jobs.set(id, st);

      console.log(`[${id}] ${r.printerId} · ${r.control || "sin control"} · ` +
        `frente ${f.w}x${f.h} (${(f.bytes/1024).toFixed(0)} KB)` +
        (b ? ` · reverso ${b.w}x${b.h}` : " · una cara") +
        (warn.length ? `\n   AVISO: ${warn.join("; ")}` : ""));

      return json(res, 202, st);
    });
    return;
  }

  json(res, 404, { error: "ruta desconocida" });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`Servicio simulado en http://127.0.0.1:${PORT}`);
  console.log(`Los PNG recibidos se guardan en ${OUT}`);
  console.log(`Tarjeta esperada: ${W} x ${H} px a ${DPI} ppp\n`);
});
