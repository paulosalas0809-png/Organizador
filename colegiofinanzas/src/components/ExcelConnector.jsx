import { useState } from "react";
import { CheckCircle2, Copy, FileSpreadsheet, Link2, PlugZap, RefreshCw, Unlink, XCircle } from "lucide-react";
import { useFinance } from "../context/FinanceContext.jsx";
import { COLUMNAS, probarConexion } from "../services/excelSync.js";
import { soles } from "../lib/format.js";

// Vinculación con el archivo de Excel Online (Power Automate) o Google Sheets (Apps Script).
const APPS_SCRIPT = `// ColegioFinanzas OS → Google Sheets
// Extensiones → Apps Script → pega esto → Implementar → Nueva implementación → Aplicación web
// Ejecutar como: Yo · Quién tiene acceso: Cualquier usuario. Copia la URL que termina en /exec.
const COLUMNAS = ["id","fecha","hora","semana","mes","tipo","categoria","concepto","monto","metodoPago","registradoPor","nOperacion"];

function doPost(e) {
  const d = JSON.parse(e.postData.contents);
  if (d.accion === "prueba") return responder({ ok: true, mensaje: "Conexión correcta" });

  const libro = SpreadsheetApp.getActiveSpreadsheet();
  const hoja = libro.getSheetByName("Movimientos") || libro.insertSheet("Movimientos");
  if (hoja.getLastRow() === 0) hoja.appendRow(COLUMNAS);

  const fila = COLUMNAS.map(function (c) { return d[c] === undefined ? "" : d[c]; });
  const ids = hoja.getLastRow() > 1 ? hoja.getRange(2, 1, hoja.getLastRow() - 1, 1).getValues().map(String) : [];
  const pos = ids.indexOf(String(d.id));           // evita duplicados si un envío se repite

  if (d.accion === "eliminar") { if (pos >= 0) hoja.deleteRow(pos + 2); }
  else if (pos >= 0) hoja.getRange(pos + 2, 1, 1, COLUMNAS.length).setValues([fila]);
  else hoja.appendRow(fila);
  return responder({ ok: true });
}

function responder(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}`;

const ESQUEMA = JSON.stringify({
  type: "object",
  properties: {
    accion: { type: "string" }, id: { type: "string" }, fecha: { type: "string" }, hora: { type: "string" },
    semana: { type: "integer" }, mes: { type: "string" }, tipo: { type: "string" }, categoria: { type: "string" },
    concepto: { type: "string" }, monto: { type: "number" }, metodoPago: { type: "string" }, registradoPor: { type: "string" },
    nOperacion: { type: "string" },
  },
}, null, 2);

export default function ExcelConnector() {
  const { datos, cola, guardarConfig, sincronizar, avisar, leerExcel, desvincularExcel } = useFinance();
  const [libro, setLibro] = useState(datos.config.excelLink || "");
  const info = datos.config.excelInfo;
  const vinculado = !!datos.config.excelLink;
  const leer = async () => { setOcupado("leer"); try { await leerExcel(libro.trim() === datos.config.excelLink ? undefined : libro.trim()); } catch (e) { /* aviso mostrado */ } setOcupado(""); };
  const desvincular = async () => {
    if (!window.confirm("¿Desvincular el Excel? Sus movimientos saldrán del tablero (tu archivo no se toca).")) return;
    setOcupado("desvincular"); try { await desvincularExcel(); setLibro(""); } catch (e) { /* aviso mostrado */ } setOcupado("");
  };
  const [url, setUrl] = useState(datos.config.webhook);
  const [prueba, setPrueba] = useState(null);
  const [ocupado, setOcupado] = useState("");
  const [guia, setGuia] = useState("sheets");
  const guardado = url.trim() === datos.config.webhook;

  const guardar = async () => { setOcupado("guardar"); try { await guardarConfig({ webhook: url.trim() }, url.trim() ? "Enlace guardado" : "Enlace quitado"); } catch (e) { /* aviso mostrado */ } setOcupado(""); };
  const probar = async () => { setOcupado("probar"); setPrueba(null); setPrueba(await probarConexion(url.trim())); setOcupado(""); };
  const enviarPendientes = async () => { setOcupado("sync"); try { await sincronizar(); } catch (e) { /* aviso mostrado */ } setOcupado(""); };
  const copiar = async (texto, que) => { try { await navigator.clipboard.writeText(texto); avisar(`${que} copiado`); } catch (e) { avisar("Selecciona el texto y cópialo a mano", "error"); } };

  return (
    <div className="space-y-4">
      <div><h1 className="text-2xl font-bold tracking-tight">Conexión directa con Excel</h1>
        <p className="text-sm text-slate-500">Cada ingreso o gasto registrado se envía solo a tu archivo. El envío sale desde el servidor: el enlace nunca llega al celular del personal.</p></div>

      <section className="card space-y-3">
        <h2 className="flex items-center gap-2 text-sm font-bold"><FileSpreadsheet size={16} />Tu libro de Excel en OneDrive (lectura automática)</h2>
        <p className="text-xs text-slate-500">El tablero lee las hojas de <b>GASTOS</b> e <b>INGRESOS</b> de tu archivo cada 15 minutos. Si una fila no tiene fecha, se usa la fecha inmediata anterior. Tu archivo no se modifica.</p>
        <label><span className="label">Enlace de «Compartir» del archivo (cualquier persona con el vínculo puede ver)</span>
          <input className="field" type="url" value={libro} onChange={(e) => setLibro(e.target.value)} placeholder="https://1drv.ms/x/…" /></label>
        <div className="flex flex-wrap gap-2">
          <button onClick={leer} disabled={!libro.trim() || ocupado} className="btn"><RefreshCw size={16} className={ocupado === "leer" ? "animate-spin" : ""} />{ocupado === "leer" ? "Leyendo tu Excel…" : vinculado && libro.trim() === datos.config.excelLink ? "Actualizar ahora" : "Vincular y leer"}</button>
          {vinculado && <button onClick={desvincular} disabled={ocupado} className="btn-sec"><Unlink size={16} />Desvincular</button>}
        </div>
        {info && !info.ok && <p className="flex items-start gap-2 rounded-xl bg-coral-50 px-3 py-2.5 text-sm font-semibold text-coral-700 dark:bg-coral-500/10 dark:text-coral-400"><XCircle size={16} className="mt-0.5 flex-none" />La última lectura falló ({info.intento}): {info.error}{info.hojas ? " Se conservan los datos de la lectura anterior." : ""}</p>}
        {info?.hojas && (
          <div className="rounded-xl bg-emerald-50 px-3 py-2.5 text-sm text-emerald-900 dark:bg-emerald-500/10 dark:text-emerald-200">
            <p className="flex items-center gap-2 font-semibold"><CheckCircle2 size={16} />Última lectura correcta: {info.cuando}</p>
            <ul className="mt-1.5 list-disc space-y-0.5 pl-6 text-xs">
              {info.hojas.map((h) => <li key={h.nombre}>Hoja «{h.nombre}»: <b className="num">{h.filas}</b> {h.tipo === "gasto" ? "gastos" : "ingresos"} · <b className="num">{soles(h.tipo === "gasto" ? info.totalGastos : info.totalIngresos)}</b></li>)}
              <li><b className="num">{info.fechasCompletadas}</b> filas sin fecha tomaron la fecha anterior · <b className="num">{info.omitidas}</b> filas omitidas por tener importe 0</li>
            </ul>
          </div>
        )}
      </section>

      <div><h2 className="text-lg font-bold tracking-tight">Envío de los registros de la Mini-App</h2>
        <p className="text-sm text-slate-500">Para que lo que registre el personal en la Mini-App se escriba solo en una hoja.</p></div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <section className="card space-y-3 lg:col-span-3">
          <h2 className="flex items-center gap-2 text-sm font-bold"><Link2 size={16} />Enlace de tu Excel o Google Sheets</h2>
          <label><span className="label">Link / Webhook (Power Automate «Cuando se recibe una solicitud HTTP», o URL /exec de Apps Script)</span>
            <input className="field" type="url" value={url} onChange={(e) => { setUrl(e.target.value); setPrueba(null); }} placeholder="https://script.google.com/macros/s/…/exec" /></label>
          <div className="flex flex-wrap gap-2">
            <button onClick={guardar} disabled={guardado || ocupado} className="btn">{ocupado === "guardar" ? "Guardando…" : guardado ? "Enlace guardado" : "Guardar enlace"}</button>
            <button onClick={probar} disabled={!url.trim() || ocupado} className="btn-sec"><PlugZap size={16} />{ocupado === "probar" ? "Probando…" : "Probar conexión con Excel"}</button>
            <button onClick={enviarPendientes} disabled={!datos.config.webhook || !cola.pendientes || ocupado} className="btn-sec"><RefreshCw size={16} className={ocupado === "sync" ? "animate-spin" : ""} />{ocupado === "sync" ? "Enviando…" : `Sincronizar pendientes (${cola.pendientes})`}</button>
          </div>
          {prueba && (
            <div className={`rounded-xl px-3 py-2.5 text-sm ${prueba.ok ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-300" : "bg-coral-50 text-coral-700 dark:bg-coral-500/10 dark:text-coral-400"}`}>
              <p className="flex items-center gap-2 font-semibold">{prueba.ok ? <CheckCircle2 size={16} /> : <XCircle size={16} />}{prueba.ok ? "Conexión correcta" : "No se pudo conectar"} · {prueba.mensaje}</p>
              {prueba.enviado && <pre className="mt-2 overflow-x-auto rounded-lg bg-black/5 p-2 text-[11px] leading-relaxed dark:bg-black/30">{JSON.stringify(prueba.enviado, null, 1)}</pre>}
            </div>
          )}
          {!guardado && <p className="text-xs text-amber-700 dark:text-amber-300">Tienes cambios sin guardar en el enlace.</p>}
        </section>

        <section className="card lg:col-span-2">
          <h2 className="mb-3 text-sm font-bold">Estado de sincronización</h2>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            {[["En Excel", cola.ok, "text-emerald-700 dark:text-emerald-400"], ["Enviando", cola.enviando, "text-amber-700 dark:text-amber-300"], ["Fallaron", cola.fallidos, "text-coral-600 dark:text-coral-400"], ["Hechos sin enlace", cola.sinEnlace, ""]].map(([t, v, c]) => (
              <div key={t} className="rounded-xl bg-slate-50 px-3 py-2.5 dark:bg-slate-800"><dt className="text-xs text-slate-500">{t}</dt><dd className={`num text-xl font-extrabold ${c}`}>{v}</dd></div>
            ))}
          </dl>
          <p className="mt-3 text-xs text-slate-500">Cada envío se reintenta solo hasta 3 veces. Los datos de ejemplo nunca se envían a tu archivo. Columnas: {COLUMNAS.join(", ")}.</p>
        </section>
      </div>

      <section className="card">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="mr-auto text-sm font-bold">Código listo para copiar</h2>
          {[["sheets", "Google Sheets (Apps Script)"], ["excel", "Excel Online (Power Automate)"]].map(([id, t]) => <button key={id} onClick={() => setGuia(id)} className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${guia === id ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"}`}>{t}</button>)}
        </div>
        {guia === "sheets" ? (
          <>
            <ol className="mb-3 list-decimal space-y-1 pl-5 text-sm text-slate-600 dark:text-slate-300">
              <li>Abre tu hoja de Google Sheets y entra a <b>Extensiones → Apps Script</b>.</li>
              <li>Borra lo que haya, pega el código y guarda.</li>
              <li><b>Implementar → Nueva implementación → Aplicación web</b>. Ejecutar como <b>Yo</b>; acceso <b>Cualquier usuario</b>.</li>
              <li>Autoriza, copia la URL que termina en <b>/exec</b>, pégala arriba y prueba la conexión.</li>
            </ol>
            <Bloque texto={APPS_SCRIPT} onCopiar={() => copiar(APPS_SCRIPT, "Código")} />
          </>
        ) : (
          <>
            <ol className="mb-3 list-decimal space-y-1 pl-5 text-sm text-slate-600 dark:text-slate-300">
              <li>En tu Excel Online crea una <b>tabla</b> con estas columnas, en este orden: <code className="text-xs">{[...COLUMNAS, "nOperacion"].join(", ")}</code>.</li>
              <li>En Power Automate crea un flujo con el desencadenador <b>«Cuando se recibe una solicitud HTTP»</b> y pega el esquema JSON de abajo.</li>
              <li>Agrega una condición: si <code className="text-xs">accion</code> es <code className="text-xs">prueba</code>, termina sin escribir.</li>
              <li>Agrega la acción <b>«Agregar una fila a una tabla»</b> (Excel Online) y asigna cada columna a su campo.</li>
              <li>Guarda, copia la <b>URL HTTP POST</b> del desencadenador, pégala arriba y prueba la conexión.</li>
            </ol>
            <Bloque texto={ESQUEMA} onCopiar={() => copiar(ESQUEMA, "Esquema JSON")} />
            <p className="mt-2 text-xs text-slate-500">Ese desencadenador requiere una licencia de Power Automate con conectores premium. Las correcciones y eliminaciones llegan con <code>accion</code> «actualizar» o «eliminar»: si quieres reflejarlas en Excel, agrega esas ramas al flujo; si no, solo se agregan filas.</p>
          </>
        )}
      </section>
    </div>
  );
}

function Bloque({ texto, onCopiar }) {
  return (
    <div className="relative">
      <button onClick={onCopiar} className="btn-sec absolute right-2 top-2 !px-2.5 !py-1.5 text-xs"><Copy size={13} />Copiar</button>
      <pre className="max-h-80 overflow-auto rounded-xl bg-slate-950 p-4 pr-24 text-xs leading-relaxed text-slate-100">{texto}</pre>
    </div>
  );
}
