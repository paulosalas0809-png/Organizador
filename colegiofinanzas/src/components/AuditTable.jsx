import { useMemo, useState } from "react";
import { Download, FileSpreadsheet, Pencil, Search, Trash2, X } from "lucide-react";
import { useFinance } from "../context/FinanceContext.jsx";
import { CATEGORIAS, MESES, METODOS, SYNC, fechaCorta, soles, suma } from "../lib/format.js";
import { COLUMNAS } from "../services/excelSync.js";

// Libro Caja: todos los movimientos, con filtros, corrección de errores y descarga para Excel.
const FILTROS0 = { q: "", semana: "", mes: "", tipo: "", categoria: "", metodo: "", usuario: "", sync: "" };
const POR_PAGINA = 50;

// Evita que Excel interprete como fórmula un texto que empieza con = + - @
const celda = (v) => { let s = String(v ?? ""); if (/^[=+\-@\t\r]/.test(s) && isNaN(Number(s))) s = `'${s}`; return /[",\n\r;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };

export default function AuditTable() {
  const { datos, editarTx, borrarTx } = useFinance();
  const [f, setF] = useState(FILTROS0);
  const [pagina, setPagina] = useState(1);
  const [edit, setEdit] = useState(null);
  const poner = (k, v) => { setF({ ...f, [k]: v }); setPagina(1); };

  const usuarios = useMemo(() => [...new Set(datos.tx.map((t) => t.registradoPor))].sort(), [datos.tx]);
  const categorias = useMemo(() => [...new Set([...CATEGORIAS.ingreso, ...CATEGORIAS.gasto, ...datos.tx.map((t) => t.categoria)])], [datos.tx]);
  const medios = useMemo(() => [...new Set([...METODOS, ...datos.tx.map((t) => t.metodoPago)])], [datos.tx]);
  const semanas = useMemo(() => [...new Set(datos.tx.map((t) => t.semana))].sort((a, b) => b - a), [datos.tx]);
  const filas = useMemo(() => {
    const q = f.q.trim().toLowerCase();
    return datos.tx.filter((t) =>
      (!q || `${t.concepto} ${t.categoria} ${t.nOperacion} ${t.registradoPor} ${t.id}`.toLowerCase().includes(q)) &&
      (!f.semana || String(t.semana) === f.semana) && (!f.mes || t.mes === f.mes) && (!f.tipo || t.tipo === f.tipo) &&
      (!f.categoria || t.categoria === f.categoria) && (!f.metodo || t.metodoPago === f.metodo) &&
      (!f.usuario || t.registradoPor === f.usuario) && (!f.sync || t.sync === f.sync)
    ).sort((a, b) => (b.fecha + b.hora).localeCompare(a.fecha + a.hora));
  }, [datos.tx, f]);
  const visibles = filas.slice(0, pagina * POR_PAGINA);
  const ing = suma(filas, "ingreso"), gas = suma(filas, "gasto");

  const descargar = () => {
    const cols = [...COLUMNAS, "nOperacion", "sync"];
    const csv = "﻿" + [cols.join(","), ...filas.map((t) => cols.map((c) => celda(t[c])).join(","))].join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = `libro-caja-${datos.hoy}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  const guardar = async (e) => {
    e.preventDefault();
    try { await editarTx(edit.id, { ...edit, monto: parseFloat(edit.monto) }); setEdit(null); } catch (err) { /* aviso mostrado */ }
  };
  const Sel = ({ k, titulo, ops }) => (
    <select aria-label={titulo} className="field !w-auto !py-2 text-xs" value={f[k]} onChange={(e) => poner(k, e.target.value)}>
      <option value="">{titulo}</option>{ops.map((o) => Array.isArray(o) ? <option key={o[0]} value={o[0]}>{o[1]}</option> : <option key={o}>{o}</option>)}
    </select>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="mr-auto"><h1 className="text-2xl font-bold tracking-tight">Libro Caja y Auditoría</h1>
          <p className="text-sm text-slate-500"><span className="num">{filas.length}</span> movimientos · ingresos <b className="num text-emerald-700 dark:text-emerald-400">{soles(ing)}</b> · gastos <b className="num text-coral-600 dark:text-coral-400">{soles(gas)}</b> · neto <b className="num">{soles(ing - gas)}</b></p></div>
        <button onClick={descargar} className="btn" disabled={!filas.length}><Download size={16} />Descargar Excel (.csv)</button>
      </div>

      <div className="card flex flex-wrap items-center gap-2 !p-3">
        <label className="relative min-w-[200px] flex-1"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input className="field !pl-9" placeholder="Buscar concepto, boleta, persona…" value={f.q} onChange={(e) => poner("q", e.target.value)} aria-label="Buscar" /></label>
        <Sel k="semana" titulo="Semana" ops={semanas.map((s) => [String(s), `Semana ${s}`])} />
        <Sel k="mes" titulo="Mes" ops={MESES} />
        <Sel k="tipo" titulo="Tipo" ops={[["ingreso", "Ingreso"], ["gasto", "Gasto"]]} />
        <Sel k="categoria" titulo="Categoría" ops={categorias} />
        <Sel k="metodo" titulo="Medio de pago" ops={medios} />
        <Sel k="usuario" titulo="Registrado por" ops={usuarios} />
        <Sel k="sync" titulo="Estado en Excel" ops={Object.entries(SYNC).map(([k, v]) => [k, v.texto])} />
        {Object.values(f).some(Boolean) && <button onClick={() => { setF(FILTROS0); setPagina(1); }} className="btn-sec !py-2 text-xs"><X size={14} />Limpiar</button>}
      </div>

      <div className="card overflow-x-auto !p-0">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800">
            <tr>{["Fecha", "Sem.", "Tipo", "Categoría / concepto", "Medio", "Registrado por", "Monto", "Excel", ""].map((h) => <th key={h} className={`px-3 py-2.5 font-semibold ${h === "Monto" ? "text-right" : ""}`}>{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {visibles.map((t) => (
              <tr key={t.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                <td className="num whitespace-nowrap px-3 py-2.5">{fechaCorta(t.fecha)}<span className="block text-xs text-slate-500">{t.origen === "excel" ? `fila ${t.fila}` : t.hora.slice(0, 5)}</span></td>
                <td className="num px-3 py-2.5 text-slate-500">{t.semana}</td>
                <td className="px-3 py-2.5"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${t.tipo === "ingreso" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" : "bg-coral-100 text-coral-700 dark:bg-coral-500/15 dark:text-coral-400"}`}>{t.tipo === "ingreso" ? "Ingreso" : "Gasto"}</span></td>
                <td className="max-w-[280px] px-3 py-2.5"><b className="block truncate font-medium">{t.concepto || "—"}</b><span className="block truncate text-xs text-slate-500">{t.categoria}{t.nOperacion ? ` · ${t.nOperacion}` : ""}{t.editado ? " · corregido" : ""}</span></td>
                <td className="whitespace-nowrap px-3 py-2.5 text-slate-600 dark:text-slate-300">{t.metodoPago}</td>
                <td className="whitespace-nowrap px-3 py-2.5 text-slate-600 dark:text-slate-300">{t.registradoPor}</td>
                <td className={`num whitespace-nowrap px-3 py-2.5 text-right font-semibold ${t.tipo === "ingreso" ? "text-emerald-700 dark:text-emerald-400" : "text-coral-600 dark:text-coral-400"}`}>{t.tipo === "ingreso" ? "+" : "−"}{soles(t.monto)}</td>
                <td className="px-3 py-2.5"><span title={t.syncMsg || ""} className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ${SYNC[t.sync]?.clase}`}>{SYNC[t.sync]?.texto || t.sync}</span></td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right">
                  {t.origen === "excel" ? <span title={`Viene de la hoja «${t.hoja}», fila ${t.fila}. Se corrige en tu Excel.`} className="inline-flex p-1.5 text-slate-400"><FileSpreadsheet size={15} /></span> : <>
                  <button onClick={() => setEdit({ ...t })} title="Editar" className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"><Pencil size={15} /></button>
                  <button onClick={() => window.confirm(`¿Eliminar este registro de ${soles(t.monto)}? No se puede deshacer.`) && borrarTx(t.id).catch(() => {})} title="Eliminar" className="rounded-lg p-1.5 text-coral-600 hover:bg-coral-50 dark:hover:bg-coral-500/10"><Trash2 size={15} /></button></>}
                </td>
              </tr>
            ))}
            {!filas.length && <tr><td colSpan={9} className="px-3 py-10 text-center text-slate-500">No hay movimientos con esos filtros.</td></tr>}
          </tbody>
        </table>
      </div>
      {visibles.length < filas.length && <div className="text-center"><button onClick={() => setPagina(pagina + 1)} className="btn-sec">Ver más ({filas.length - visibles.length} restantes)</button></div>}

      {edit && (
        <div className="fixed inset-0 z-40 grid place-items-center bg-slate-950/60 p-4" onMouseDown={(e) => e.target === e.currentTarget && setEdit(null)}>
          <form onSubmit={guardar} className="card w-full max-w-lg space-y-3">
            <div className="flex items-center"><h2 className="flex-1 text-base font-bold">Corregir registro</h2><button type="button" onClick={() => setEdit(null)} className="text-slate-500"><X size={18} /></button></div>
            <div className="grid grid-cols-2 gap-3">
              <label><span className="label">Fecha</span><input type="date" className="field" value={edit.fecha} max={datos.hoy} onChange={(e) => setEdit({ ...edit, fecha: e.target.value })} required /></label>
              <label><span className="label">Monto (S/)</span><input type="number" min="0.01" step="0.01" className="field num" value={edit.monto} onChange={(e) => setEdit({ ...edit, monto: e.target.value })} required /></label>
              <label><span className="label">Tipo</span><select className="field" value={edit.tipo} onChange={(e) => setEdit({ ...edit, tipo: e.target.value, categoria: CATEGORIAS[e.target.value][0] })}><option value="ingreso">Ingreso</option><option value="gasto">Gasto</option></select></label>
              <label><span className="label">Categoría</span><select className="field" value={edit.categoria} onChange={(e) => setEdit({ ...edit, categoria: e.target.value })}>{CATEGORIAS[edit.tipo].map((c) => <option key={c}>{c}</option>)}</select></label>
              <label><span className="label">Medio de pago</span><select className="field" value={edit.metodoPago} onChange={(e) => setEdit({ ...edit, metodoPago: e.target.value })}>{METODOS.map((m) => <option key={m}>{m}</option>)}</select></label>
              <label><span className="label">N.° operación / boleta</span><input className="field" maxLength={40} value={edit.nOperacion || ""} onChange={(e) => setEdit({ ...edit, nOperacion: e.target.value })} /></label>
              <label className="col-span-2"><span className="label">Concepto</span><input className="field" maxLength={120} value={edit.concepto || ""} onChange={(e) => setEdit({ ...edit, concepto: e.target.value })} /></label>
            </div>
            <p className="text-xs text-slate-500">Registrado por {edit.registradoPor}. La corrección queda marcada y, si ya estaba en Excel, se actualiza allí también.</p>
            <div className="flex justify-end gap-2"><button type="button" onClick={() => setEdit(null)} className="btn-sec">Cancelar</button><button className="btn">Guardar corrección</button></div>
          </form>
        </div>
      )}
    </div>
  );
}
