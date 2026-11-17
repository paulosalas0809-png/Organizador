import { useEffect, useState } from "react";
import { ArrowDownCircle, ArrowUpCircle, Check, Delete, GraduationCap, LogOut, ShieldAlert, UserRound } from "lucide-react";
import { useFinance } from "../context/FinanceContext.jsx";
import { CATEGORIAS, METODOS, SYNC, soles } from "../lib/format.js";

// Mini-App móvil para el personal autorizado: registra ingresos y gastos en tres toques.
// Nunca muestra saldos ni totales del colegio: solo los últimos 5 registros propios del día.
export default function MiniAppCaja({ incrustada = false }) {
  const { caja, cargarCaja } = useFinance();
  useEffect(() => { cargarCaja(); }, [cargarCaja]);
  // Se vuelve a comprobar el acceso cada 30 s: si Dirección bloquea a la persona, sale sola
  useEffect(() => {
    const t = setInterval(() => { if (!document.hidden) cargarCaja(); }, 30000);
    return () => clearInterval(t);
  }, [cargarCaja]);

  return (
    <div className={incrustada ? "" : "mx-auto min-h-screen max-w-md px-3 pb-10 pt-4"}>
      {!caja.listo ? <p className="p-16 text-center text-sm text-slate-500">Cargando…</p> : caja.usuario ? <Registro /> : <Ingreso />}
    </div>
  );
}

function Ingreso() {
  const { caja, entrarCaja } = useFinance();
  const [perfil, setPerfil] = useState(null);
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");

  const tocar = async (d) => {
    if (pin.length >= 4) return;
    const nuevo = pin + d;
    setPin(nuevo); setError("");
    if (nuevo.length === 4) {
      try { await entrarCaja(nuevo, perfil?.id); } catch (e) { setError(e.message); setPin(""); }
    }
  };

  return (
    <div className="pt-6 text-center">
      <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-indigo-600 text-white"><GraduationCap size={26} /></span>
      <h1 className="mt-3 text-xl font-bold tracking-tight">Caja del colegio</h1>
      <p className="text-sm text-slate-500">{caja.colegio || "Registro rápido de ingresos y gastos"}</p>

      {caja.perfiles.length > 0 && (
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          {caja.perfiles.map((p) => (
            <button key={p.id} onClick={() => { setPerfil(perfil?.id === p.id ? null : p); setPin(""); setError(""); }}
              className={`flex items-center gap-2 rounded-full border px-3.5 py-2 text-sm font-medium transition ${perfil?.id === p.id ? "border-indigo-600 bg-indigo-600 text-white" : "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800"}`}>
              <UserRound size={15} />{p.cargo ? `${p.cargo} - ${p.nombre}` : p.nombre}
            </button>
          ))}
        </div>
      )}

      <p className="mt-6 text-sm font-medium">{perfil ? `PIN de ${perfil.nombre}` : "Ingresa tu PIN de 4 dígitos"}</p>
      <div className="mt-3 flex justify-center gap-3" aria-label={`${pin.length} de 4 dígitos`}>
        {[0, 1, 2, 3].map((i) => <i key={i} className={`h-3.5 w-3.5 rounded-full ${i < pin.length ? "bg-indigo-600" : "bg-slate-300 dark:bg-slate-700"}`} />)}
      </div>
      {caja.bloqueado && !error && <p className="mx-auto mt-4 flex max-w-xs items-center justify-center gap-2 rounded-xl bg-coral-50 px-3 py-2 text-sm text-coral-700 dark:bg-coral-500/10 dark:text-coral-400"><ShieldAlert size={16} />Tu acceso fue bloqueado por Dirección.</p>}
      {error && <p className="mx-auto mt-4 flex max-w-xs items-center justify-center gap-2 rounded-xl bg-coral-50 px-3 py-2 text-sm text-coral-700 dark:bg-coral-500/10 dark:text-coral-400"><ShieldAlert size={16} />{error}</p>}

      <div className="mx-auto mt-6 grid max-w-[17rem] grid-cols-3 gap-3">
        {["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "←"].map((d, i) => d === "" ? <span key={i} /> : (
          <button key={i} onClick={() => (d === "←" ? setPin(pin.slice(0, -1)) : tocar(d))} aria-label={d === "←" ? "Borrar" : d}
            className="grid h-16 place-items-center rounded-2xl border border-slate-200 bg-white text-2xl font-semibold shadow-sm active:scale-95 dark:border-slate-700 dark:bg-slate-800">
            {d === "←" ? <Delete size={22} /> : d}
          </button>
        ))}
      </div>
    </div>
  );
}

const VACIO = { monto: "", categoria: "", metodoPago: "Efectivo", concepto: "", nOperacion: "" };

function Registro() {
  const { caja, registrar, salirCaja } = useFinance();
  const u = caja.usuario;
  const tipos = u.permiso === "ingresos" ? ["ingreso"] : u.permiso === "gastos" ? ["gasto"] : ["ingreso", "gasto"];
  const [tipo, setTipo] = useState(tipos[0]);
  const [f, setF] = useState(VACIO);
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [hecho, setHecho] = useState(false);
  const monto = parseFloat(String(f.monto).replace(",", ".")) || 0;
  const pasaTope = u.tope > 0 && monto > u.tope;
  const esIngreso = tipo === "ingreso";

  const enviar = async (e) => {
    e.preventDefault();
    if (!(monto > 0)) return setError("Escribe el monto.");
    if (!f.categoria) return setError("Elige una categoría.");
    setEnviando(true); setError("");
    try {
      await registrar({ tipo, ...f, monto });
      setF(VACIO); setHecho(true); setTimeout(() => setHecho(false), 2200);
    } catch (err) { setError(err.message); }
    setEnviando(false);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <span className="grid h-10 w-10 place-items-center rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300"><UserRound size={19} /></span>
        <div className="min-w-0 flex-1 leading-tight">
          <b className="block truncate text-sm">{u.cargo ? `${u.cargo} - ${u.nombre}` : u.nombre}</b>
          <span className="text-xs text-slate-500">{u.tope > 0 ? `Tope por operación ${soles(u.tope)}` : "Sin tope por operación"}</span>
        </div>
        <button onClick={salirCaja} className="btn-sec !px-3 !py-2" title="Salir"><LogOut size={16} /></button>
      </div>

      <form onSubmit={enviar} className="card space-y-4 !p-4">
        {/* Toque 1: ingreso o gasto (se oculta el que la persona no tiene permitido) */}
        <div className={`grid gap-2 ${tipos.length > 1 ? "grid-cols-2" : "grid-cols-1"}`}>
          {tipos.map((t) => {
            const activo = tipo === t, ing = t === "ingreso";
            return (
              <button type="button" key={t} onClick={() => { setTipo(t); setF({ ...f, categoria: "" }); }}
                className={`flex items-center justify-center gap-2 rounded-2xl py-4 text-base font-bold transition ${activo ? (ing ? "bg-emerald-600 text-white shadow-lg shadow-emerald-600/25" : "bg-coral-500 text-white shadow-lg shadow-coral-500/25") : "bg-slate-100 text-slate-500 dark:bg-slate-800"}`}>
                {ing ? <ArrowDownCircle size={20} /> : <ArrowUpCircle size={20} />}{ing ? "+ INGRESO" : "− GASTO"}
              </button>
            );
          })}
        </div>

        {/* Toque 2: monto */}
        <label className="block text-center">
          <span className="label">Monto en Soles</span>
          <div className={`flex items-center justify-center gap-2 rounded-2xl border-2 px-4 py-3 ${pasaTope ? "border-coral-500" : esIngreso ? "border-emerald-500/40" : "border-coral-400/40"}`}>
            <span className="text-2xl font-bold text-slate-400">S/</span>
            <input inputMode="decimal" value={f.monto} onChange={(e) => setF({ ...f, monto: e.target.value.replace(/[^\d.,]/g, "") })} placeholder="0.00"
              aria-label="Monto en Soles" className="num w-full bg-transparent text-center text-4xl font-extrabold tracking-tight outline-none placeholder:text-slate-300 dark:placeholder:text-slate-700" />
          </div>
          {pasaTope && <span className="mt-1 block text-xs font-medium text-coral-600">Supera tu tope de {soles(u.tope)}. Pide a Dirección que lo registre.</span>}
        </label>

        {/* Toque 3: categoría */}
        <div>
          <span className="label">Categoría</span>
          <div className="flex flex-wrap gap-2">
            {CATEGORIAS[tipo].map((c) => <Opcion key={c} activa={f.categoria === c} onClick={() => setF({ ...f, categoria: c })} color={esIngreso ? "emerald" : "coral"}>{c}</Opcion>)}
          </div>
        </div>
        <div>
          <span className="label">Método de pago</span>
          <div className="grid grid-cols-2 gap-2">
            {METODOS.map((m) => <Opcion key={m} activa={f.metodoPago === m} onClick={() => setF({ ...f, metodoPago: m })} color="indigo" bloque>{m}</Opcion>)}
          </div>
        </div>
        <div className="grid grid-cols-5 gap-2">
          <label className="col-span-3"><span className="label">Concepto</span>
            <input className="field" maxLength={120} value={f.concepto} onChange={(e) => setF({ ...f, concepto: e.target.value })} placeholder={esIngreso ? "Alumno y grado" : "Proveedor"} /></label>
          <label className="col-span-2"><span className="label">N.° operación / boleta</span>
            <input className="field" maxLength={40} value={f.nOperacion} onChange={(e) => setF({ ...f, nOperacion: e.target.value })} placeholder="Opcional" /></label>
        </div>

        {error && <p className="rounded-xl bg-coral-50 px-3 py-2 text-sm text-coral-700 dark:bg-coral-500/10 dark:text-coral-400">{error}</p>}
        <button disabled={enviando || pasaTope} className={`flex w-full items-center justify-center gap-2 rounded-2xl py-4 text-base font-bold text-white transition disabled:opacity-50 ${hecho ? "bg-slate-900 dark:bg-slate-700" : esIngreso ? "bg-emerald-600 hover:bg-emerald-500" : "bg-coral-500 hover:bg-coral-600"}`}>
          {hecho ? <><Check size={20} />Registrado</> : enviando ? "Enviando…" : `Registrar ${esIngreso ? "ingreso" : "gasto"}${monto > 0 ? ` de ${soles(monto)}` : ""}`}
        </button>
      </form>

      <section>
        <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wider text-slate-500">Tus últimos registros de hoy</h2>
        {caja.recientes.length === 0 ? <p className="card !p-4 text-sm text-slate-500">Aún no registras movimientos hoy.</p> : (
          <ul className="card divide-y divide-slate-100 !p-0 dark:divide-slate-800">
            {caja.recientes.map((t) => (
              <li key={t.id} className="flex items-center gap-3 px-4 py-3">
                <span className={`grid h-9 w-9 flex-none place-items-center rounded-full ${t.tipo === "ingreso" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" : "bg-coral-100 text-coral-700 dark:bg-coral-500/15 dark:text-coral-400"}`}>
                  {t.tipo === "ingreso" ? <ArrowDownCircle size={18} /> : <ArrowUpCircle size={18} />}</span>
                <div className="min-w-0 flex-1 leading-tight">
                  <b className="block truncate text-sm">{t.concepto || t.categoria}</b>
                  <span className="text-xs text-slate-500">{t.hora.slice(0, 5)} · {t.categoria} · {t.metodoPago}</span>
                </div>
                <div className="text-right leading-tight">
                  <b className={`num block text-sm ${t.tipo === "ingreso" ? "text-emerald-700 dark:text-emerald-400" : "text-coral-600 dark:text-coral-400"}`}>{t.tipo === "ingreso" ? "+" : "−"}{soles(t.monto).replace("S/ ", "S/ ")}</b>
                  <span className={`mt-0.5 inline-block rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${SYNC[t.sync]?.clase}`}>{SYNC[t.sync]?.texto}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

const COLOR = {
  emerald: "border-emerald-600 bg-emerald-600 text-white",
  coral: "border-coral-500 bg-coral-500 text-white",
  indigo: "border-indigo-600 bg-indigo-600 text-white",
};
function Opcion({ activa, onClick, children, color, bloque }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={activa}
      className={`rounded-xl border px-3 py-2 text-sm font-medium transition ${bloque ? "w-full" : ""} ${activa ? COLOR[color] : "border-slate-200 bg-white text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"}`}>
      {children}
    </button>
  );
}
