import { useMemo, useState } from "react";
import { Copy, MessageCircle, Pencil, Plus, Trash2, UserRound, X } from "lucide-react";
import { useFinance } from "../context/FinanceContext.jsx";
import { PERMISOS, soles } from "../lib/format.js";

// Dirección decide quién usa la Mini-App, con qué PIN, qué puede registrar y hasta qué monto.
const enlaceCaja = () => `${window.location.origin}${window.location.pathname}?view=caja`;
const NUEVO = { nombre: "", cargo: "", pin: "", permiso: "ambos", tope: 500, activo: true };

export default function AccessManager() {
  const { datos, crearUsuario, editarUsuario, borrarUsuario, avisar } = useFinance();
  const [form, setForm] = useState(null);       // null | {…usuario}
  const stats = useMemo(() => datos.tx.reduce((a, t) => {
    const s = (a[t.userId] ||= { n: 0, monto: 0 });
    s.n += 1; s.monto += t.monto;
    return a;
  }, {}), [datos.tx]);

  const copiar = async () => {
    try { await navigator.clipboard.writeText(enlaceCaja()); avisar("Link de la Mini-App copiado"); }
    catch (e) { window.prompt("Copia el link de la Mini-App:", enlaceCaja()); }
  };
  const whatsapp = (u) => {
    const texto = `Hola ${u.nombre}, este es tu acceso a la caja del colegio.\n\nLink: ${enlaceCaja()}\nTu PIN: ${u.pin}\n\nNo compartas tu PIN con nadie.`;
    window.open(`https://wa.me/?text=${encodeURIComponent(texto)}`, "_blank", "noopener");
  };
  const guardar = async (e) => {
    e.preventDefault();
    const { id, ...campos } = form;
    try { await (id ? editarUsuario(id, campos) : crearUsuario(campos)); setForm(null); } catch (err) { /* el aviso ya se mostró */ }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="mr-auto"><h1 className="text-2xl font-bold tracking-tight">Accesos a la Mini-App</h1>
          <p className="text-sm text-slate-500">{datos.usuarios.filter((u) => u.activo).length} de {datos.usuarios.length} personas con acceso activo. Los cambios se aplican al instante.</p></div>
        <button onClick={copiar} className="btn-sec"><Copy size={16} />Copiar link de Mini-App (?view=caja)</button>
        <button onClick={() => setForm({ ...NUEVO })} className="btn"><Plus size={16} />Autorizar nueva persona</button>
      </div>

      {datos.usuarios.length === 0 && <p className="card text-sm text-slate-500">Todavía no autorizas a nadie. Usa «Autorizar nueva persona».</p>}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {datos.usuarios.map((u) => {
          const s = stats[u.id] || { n: 0, monto: 0 };
          return (
            <article key={u.id} className={`card space-y-3 ${u.activo ? "" : "opacity-70"}`}>
              <div className="flex items-start gap-3">
                <span className="grid h-10 w-10 flex-none place-items-center rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300"><UserRound size={19} /></span>
                <div className="min-w-0 flex-1 leading-tight"><b className="block truncate">{u.cargo ? `${u.cargo} - ${u.nombre}` : u.nombre}</b>
                  <span className={`text-xs font-semibold ${u.activo ? "text-emerald-700 dark:text-emerald-400" : "text-coral-600 dark:text-coral-400"}`}>{u.activo ? "Acceso activo" : "Acceso bloqueado"}</span></div>
                <button role="switch" aria-checked={u.activo} aria-label={`Acceso de ${u.nombre}`} onClick={() => editarUsuario(u.id, { activo: !u.activo }, u.activo ? `${u.nombre} quedó bloqueado` : `${u.nombre} tiene acceso otra vez`).catch(() => {})}
                  className={`relative h-6 w-11 flex-none rounded-full transition ${u.activo ? "bg-emerald-600" : "bg-slate-300 dark:bg-slate-700"}`}>
                  <i className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${u.activo ? "translate-x-5" : ""}`} /></button>
              </div>
              <dl className="grid grid-cols-3 gap-2 text-xs">
                <Dato t="PIN" v={<span className="num tracking-widest">{u.pin}</span>} /><Dato t="Permiso" v={PERMISOS[u.permiso]} /><Dato t="Tope por registro" v={u.tope > 0 ? soles(u.tope, 0) : "Sin tope"} />
              </dl>
              <p className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300"><b className="num">{s.n}</b> registros · <b className="num">{soles(s.monto)}</b> procesados</p>
              <div className="flex gap-2">
                <button onClick={() => whatsapp(u)} className="btn-sec flex-1 !py-2 text-xs"><MessageCircle size={15} />Enviar por WhatsApp</button>
                <button onClick={() => setForm({ ...u })} className="btn-sec !px-3 !py-2" title="Editar"><Pencil size={15} /></button>
                <button onClick={() => window.confirm(`¿Quitar el acceso de ${u.nombre}? Sus registros se conservan.`) && borrarUsuario(u.id).catch(() => {})} className="btn-sec !px-3 !py-2 text-coral-600" title="Eliminar"><Trash2 size={15} /></button>
              </div>
            </article>
          );
        })}
      </div>

      {form && (
        <div className="fixed inset-0 z-40 grid place-items-center bg-slate-950/60 p-4" onMouseDown={(e) => e.target === e.currentTarget && setForm(null)}>
          <form onSubmit={guardar} className="card w-full max-w-md space-y-3">
            <div className="flex items-center"><h2 className="flex-1 text-base font-bold">{form.id ? "Editar acceso" : "Autorizar nueva persona"}</h2><button type="button" onClick={() => setForm(null)} className="text-slate-500"><X size={18} /></button></div>
            <div className="grid grid-cols-2 gap-3">
              <label><span className="label">Nombre</span><input className="field" required maxLength={40} value={form.nombre} onChange={(e) => setForm({ ...form, nombre: e.target.value })} placeholder="Ana" autoFocus /></label>
              <label><span className="label">Cargo</span><input className="field" maxLength={40} value={form.cargo} onChange={(e) => setForm({ ...form, cargo: e.target.value })} placeholder="Secretaría" /></label>
              <label><span className="label">PIN de 4 dígitos</span><input className="field num tracking-widest" required inputMode="numeric" pattern="\d{4}" maxLength={4} value={form.pin} onChange={(e) => setForm({ ...form, pin: e.target.value.replace(/\D/g, "") })} placeholder="0000" /></label>
              <label><span className="label">Monto máximo por registro (S/)</span><input className="field num" type="number" min="0" step="1" value={form.tope} onChange={(e) => setForm({ ...form, tope: e.target.value })} /></label>
              <label className="col-span-2"><span className="label">Permiso</span>
                <select className="field" value={form.permiso} onChange={(e) => setForm({ ...form, permiso: e.target.value })}>{Object.entries(PERMISOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            </div>
            <p className="text-xs text-slate-500">Deja el monto máximo en 0 para no poner tope.</p>
            <div className="flex justify-end gap-2"><button type="button" onClick={() => setForm(null)} className="btn-sec">Cancelar</button><button className="btn">Guardar</button></div>
          </form>
        </div>
      )}
    </div>
  );
}

const Dato = ({ t, v }) => <div><dt className="text-slate-500">{t}</dt><dd className="mt-0.5 font-semibold">{v}</dd></div>;
