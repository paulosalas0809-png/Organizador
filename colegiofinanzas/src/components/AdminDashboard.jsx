import { useMemo, useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BookOpenCheck, FileSpreadsheet, KeyRound, LayoutDashboard, Pencil, ShieldAlert, Sparkles, TrendingDown, TrendingUp, Users, Wallet } from "lucide-react";
import { useFinance } from "../context/FinanceContext.jsx";
import { MESES, entre, fecha, iso, lunesDe, masDias, soles, solesCorto, suma, variacion } from "../lib/format.js";
import AccessManager from "./AccessManager.jsx";
import AuditTable from "./AuditTable.jsx";
import ExcelConnector from "./ExcelConnector.jsx";

const VERDE = "#059669", CORAL = "#f4574b";
const PALETA = ["#6366f1", "#0ea5e9", "#f59e0b", "#14b8a6", "#ec4899"];
const PESTANAS = [
  ["tablero", "Dashboard", LayoutDashboard],
  ["accesos", "Accesos a la Mini-App", Users],
  ["libro", "Libro Caja y Auditoría", BookOpenCheck],
  ["excel", "Conexión con Excel", FileSpreadsheet],
];

export default function AdminDashboard() {
  const { datos, cola, limpiarEjemplo, guardarConfig } = useFinance();
  const [pestana, setPestana] = useState("tablero");
  if (!datos) return <p className="p-16 text-center text-sm text-slate-500">Cargando…</p>;

  const cambiarPin = () => {
    const pin = window.prompt("Nuevo PIN de Dirección (4 dígitos):");
    if (pin === null) return;
    if (!/^\d{4}$/.test(pin)) return window.alert("El PIN debe tener exactamente 4 dígitos.");
    guardarConfig({ pinNuevo: pin }, "PIN de Dirección actualizado").catch(() => {});
  };

  return (
    <div className="mx-auto max-w-7xl px-4 pb-16 pt-4">
      {datos.pinPorDefecto && (
        <Aviso icono={ShieldAlert} tono="coral" texto="El PIN de Dirección sigue siendo 0000. Cualquiera que tenga el enlace podría entrar: cámbialo ahora.">
          <button onClick={cambiarPin} className="btn-sec !py-1.5 text-xs"><KeyRound size={14} />Cambiar PIN</button>
        </Aviso>
      )}
      {datos.demo && (
        <Aviso icono={Sparkles} tono="amber" texto="Estás viendo datos de ejemplo de un colegio (incluye 3 usuarios con PIN 1111, 2222 y 3333). Bórralos antes de usar la app de verdad.">
          <button onClick={() => window.confirm("¿Borrar todos los movimientos y usuarios de ejemplo? No se puede deshacer.") && limpiarEjemplo().catch(() => {})} className="btn-sec !py-1.5 text-xs">Limpiar datos de ejemplo</button>
        </Aviso>
      )}

      <nav className="mb-5 flex gap-1 overflow-x-auto rounded-2xl border border-slate-200 bg-white p-1 dark:border-slate-800 dark:bg-slate-900" aria-label="Secciones">
        {PESTANAS.map(([id, texto, Icono]) => (
          <button key={id} onClick={() => setPestana(id)} className={`flex flex-none items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold transition ${pestana === id ? "bg-indigo-600 text-white" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"}`}>
            <Icono size={16} />{texto}
            {id === "excel" && cola.pendientes > 0 && <span className="rounded-full bg-amber-400 px-1.5 text-[11px] font-bold text-amber-950">{cola.pendientes}</span>}
          </button>
        ))}
        {!datos.pinPorDefecto && <button onClick={cambiarPin} className="ml-auto flex flex-none items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"><KeyRound size={14} />Cambiar PIN</button>}
      </nav>

      {pestana === "tablero" && <Tablero />}
      {pestana === "accesos" && <AccessManager />}
      {pestana === "libro" && <AuditTable />}
      {pestana === "excel" && <ExcelConnector />}
    </div>
  );
}

function Aviso({ icono: Icono, tono, texto, children }) {
  const clase = tono === "coral" ? "border-coral-400/40 bg-coral-50 text-coral-700 dark:bg-coral-500/10 dark:text-coral-400" : "border-amber-400/40 bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-300";
  return <div className={`mb-3 flex flex-wrap items-center gap-3 rounded-2xl border px-4 py-2.5 text-sm ${clase}`}><Icono size={17} className="flex-none" /><span className="min-w-0 flex-1">{texto}</span>{children}</div>;
}

// ---------------------------------------------------------------- Dashboard semanal y mensual

const FILTROS = [["semana", "Esta Semana"], ["mes", "Este Mes"], ["mesAnterior", "Mes Anterior"], ["anio", "Todo el Año"]];

function Tablero() {
  const { datos, guardarConfig } = useFinance();
  const [ref, setRef] = useState(datos.hoy);
  const [filtro, setFiltro] = useState("mes");
  const meta = datos.config.metaMensual || 0;

  const k = useMemo(() => {
    const tx = datos.tx, d = fecha(ref), anio = d.getFullYear(), mes = d.getMonth();
    const lun = lunesDe(d), semana = entre(tx, iso(lun), iso(masDias(lun, 6))), semAnt = entre(tx, iso(masDias(lun, -7)), iso(masDias(lun, -1)));
    const rangoMes = (a, m) => [iso(new Date(a, m, 1, 12)), iso(new Date(a, m + 1, 0, 12))];
    const delMes = entre(tx, ...rangoMes(anio, mes));
    const diasMes = new Date(anio, mes + 1, 0).getDate();
    const semanas = Array.from({ length: Math.ceil(diasMes / 7) }, (_, i) => {
      const a = iso(new Date(anio, mes, i * 7 + 1, 12)), b = iso(new Date(anio, mes, Math.min(diasMes, i * 7 + 7), 12));
      const s = entre(tx, a, b);
      return { nombre: `Semana ${i + 1}`, rango: `${i * 7 + 1}–${Math.min(diasMes, i * 7 + 7)} ${MESES[mes].slice(0, 3).toLowerCase()}`, Ingresos: suma(s, "ingreso"), Gastos: suma(s, "gasto") };
    });
    // Los meses que todavía no llegan quedan vacíos (no en cero) para que la curva no se desplome
    const hoy = fecha(datos.hoy), futuro = (i) => anio > hoy.getFullYear() || (anio === hoy.getFullYear() && i > hoy.getMonth());
    const meses = MESES.map((m, i) => { const s = entre(tx, ...rangoMes(anio, i)); return { nombre: m.slice(0, 3), mes: m, Ingresos: futuro(i) ? null : suma(s, "ingreso"), Gastos: futuro(i) ? null : suma(s, "gasto") }; });
    const periodo = filtro === "semana" ? semana : filtro === "mes" ? delMes : filtro === "mesAnterior" ? entre(tx, ...rangoMes(anio, mes - 1)) : entre(tx, `${anio}-01-01`, `${anio}-12-31`);
    const agrupar = (xs, campo) => Object.entries(xs.reduce((a, t) => ({ ...a, [t[campo]]: (a[t[campo]] || 0) + t.monto }), {})).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
    return {
      semIng: suma(semana, "ingreso"), semGas: suma(semana, "gasto"), antIng: suma(semAnt, "ingreso"), antGas: suma(semAnt, "gasto"),
      mesIng: suma(delMes, "ingreso"), mesGas: suma(delMes, "gasto"), nombreMes: MESES[mes], anio,
      rangoSemana: `${lun.getDate()}–${masDias(lun, 6).getDate()} ${MESES[masDias(lun, 6).getMonth()].slice(0, 3).toLowerCase()}`,
      semanas, meses, n: periodo.length,
      ingCat: agrupar(periodo.filter((t) => t.tipo === "ingreso"), "categoria"), gasCat: agrupar(periodo.filter((t) => t.tipo === "gasto"), "categoria"),
      medios: agrupar(periodo, "metodoPago"),
    };
  }, [datos.tx, datos.hoy, ref, filtro]);

  const neto = k.mesIng - k.mesGas;
  const editarMeta = () => {
    const v = window.prompt("Meta de ingresos del mes (S/):", meta);
    if (v === null) return;
    const n = parseFloat(String(v).replace(/[^\d.]/g, ""));
    if (isFinite(n)) guardarConfig({ metaMensual: n }, "Meta mensual actualizada").catch(() => {});
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="mr-auto">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{k.nombreMes} {k.anio} · semana del {k.rangoSemana}</p>
          <h1 className="text-2xl font-bold tracking-tight">Resumen financiero</h1>
        </div>
        <div className="flex gap-1 rounded-xl border border-slate-200 bg-white p-1 dark:border-slate-800 dark:bg-slate-900">
          {FILTROS.map(([id, t]) => <button key={id} onClick={() => setFiltro(id)} className={`rounded-lg px-2.5 py-1.5 text-xs font-semibold ${filtro === id ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "text-slate-500"}`}>{t}</button>)}
        </div>
        <label className="text-xs font-semibold text-slate-500">Fecha de referencia
          <input type="date" value={ref} max={datos.hoy} onChange={(e) => e.target.value && setRef(e.target.value)} className="field mt-1 !py-1.5" /></label>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi titulo="Ingresos semanales" valor={k.semIng} icono={TrendingUp} color="emerald" pie={<Variacion v={variacion(k.semIng, k.antIng)} buenoSiSube />} />
        <Kpi titulo="Gastos semanales" valor={k.semGas} icono={TrendingDown} color="coral" pie={<Variacion v={variacion(k.semGas, k.antGas)} />} />
        <Kpi titulo={`Ingresos de ${k.nombreMes.toLowerCase()}`} valor={k.mesIng} icono={Wallet} color="emerald"
          pie={meta > 0 ? (
            <div>
              <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800"><div className="h-full rounded-full bg-emerald-600" style={{ width: `${Math.min(100, (k.mesIng / meta) * 100)}%` }} /></div>
              <button onClick={editarMeta} className="mt-1.5 flex items-center gap-1 text-xs text-slate-500 hover:text-slate-900 dark:hover:text-white">{Math.round((k.mesIng / meta) * 100)}% de la meta de {soles(meta, 0)}<Pencil size={11} /></button>
            </div>
          ) : <button onClick={editarMeta} className="text-xs font-semibold text-indigo-600">Definir meta mensual</button>} />
        <Kpi titulo={`Gastos de ${k.nombreMes.toLowerCase()}`} valor={k.mesGas} icono={TrendingDown} color="coral"
          pie={<p className="text-xs text-slate-500">Flujo neto del mes <b className={`num ml-1 text-sm ${neto >= 0 ? "text-emerald-700 dark:text-emerald-400" : "text-coral-600 dark:text-coral-400"}`}>{neto >= 0 ? "+" : ""}{soles(neto)}</b></p>} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section className="card">
          <Titulo t="Ingresos vs. gastos por semana" s={`${k.nombreMes} ${k.anio}`} />
          <div className="h-64"><ResponsiveContainer>
            <BarChart data={k.semanas} margin={{ top: 8, right: 4, left: 0, bottom: 0 }} barGap={3}>
              <CartesianGrid vertical={false} strokeOpacity={0.15} /><XAxis dataKey="nombre" tickLine={false} axisLine={false} /><YAxis tickLine={false} axisLine={false} width={54} tickFormatter={solesCorto} />
              <Tooltip cursor={{ fillOpacity: 0.06 }} content={<Detalle campo="rango" />} /><Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="Ingresos" fill={VERDE} radius={[4, 4, 0, 0]} maxBarSize={30} /><Bar dataKey="Gastos" fill={CORAL} radius={[4, 4, 0, 0]} maxBarSize={30} />
            </BarChart></ResponsiveContainer></div>
        </section>
        <section className="card">
          <Titulo t="Evolución mensual" s={`Enero a diciembre de ${k.anio}`} />
          <div className="h-64"><ResponsiveContainer>
            <AreaChart data={k.meses} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="gi" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={VERDE} stopOpacity={0.3} /><stop offset="1" stopColor={VERDE} stopOpacity={0} /></linearGradient>
                <linearGradient id="gg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={CORAL} stopOpacity={0.25} /><stop offset="1" stopColor={CORAL} stopOpacity={0} /></linearGradient>
              </defs>
              <CartesianGrid vertical={false} strokeOpacity={0.15} /><XAxis dataKey="nombre" tickLine={false} axisLine={false} /><YAxis tickLine={false} axisLine={false} width={54} tickFormatter={solesCorto} />
              <Tooltip content={<Detalle campo="mes" />} /><Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
              <Area type="monotone" dataKey="Ingresos" stroke={VERDE} strokeWidth={2} fill="url(#gi)" /><Area type="monotone" dataKey="Gastos" stroke={CORAL} strokeWidth={2} fill="url(#gg)" />
            </AreaChart></ResponsiveContainer></div>
        </section>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Anillo titulo="Ingresos por categoría" datos={k.ingCat} />
        <Anillo titulo="Gastos por categoría" datos={k.gasCat} />
        <Anillo titulo="Medios de pago" datos={k.medios} />
      </div>
      <p className="text-xs text-slate-500">Los tres anillos corresponden a: {FILTROS.find((f) => f[0] === filtro)[1].toLowerCase()} ({k.n} movimientos). Las tarjetas y los dos gráficos superiores siguen la fecha de referencia.</p>
    </div>
  );
}

const Titulo = ({ t, s }) => <div className="mb-3"><h2 className="text-sm font-bold">{t}</h2><p className="text-xs text-slate-500">{s}</p></div>;

function Kpi({ titulo, valor, icono: Icono, color, pie }) {
  const tono = color === "emerald" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" : "bg-coral-100 text-coral-700 dark:bg-coral-500/15 dark:text-coral-400";
  return (
    <div className="card flex flex-col gap-3">
      <div className="flex items-center justify-between"><span className="text-xs font-semibold text-slate-500">{titulo}</span><span className={`grid h-8 w-8 place-items-center rounded-lg ${tono}`}><Icono size={16} /></span></div>
      <b className="num text-2xl font-extrabold tracking-tight">{soles(valor)}</b>
      <div className="mt-auto">{pie}</div>
    </div>
  );
}

function Variacion({ v, buenoSiSube = false }) {
  if (v === null) return <p className="text-xs text-slate-500">Sin datos de la semana anterior</p>;
  const sube = v >= 0, bueno = sube === buenoSiSube;
  return <p className="text-xs text-slate-500"><b className={`num mr-1 ${bueno ? "text-emerald-700 dark:text-emerald-400" : "text-coral-600 dark:text-coral-400"}`}>{sube ? "▲" : "▼"} {Math.abs(v).toFixed(1)}%</b>vs. semana anterior</p>;
}

function Detalle({ active, payload, campo }) {
  if (!active || !payload?.length) return null;
  const fila = payload[0].payload;
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-800">
      <b className="mb-1 block">{fila.nombre}{campo && fila[campo] && fila[campo] !== fila.nombre ? ` · ${fila[campo]}` : ""}</b>
      {payload.filter((p) => p.value != null).map((p) => <div key={p.dataKey} className="flex items-center justify-between gap-4"><span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: p.color }} />{p.dataKey}</span><span className="num font-semibold">{soles(p.value)}</span></div>)}
      {payload.length === 2 && <div className="mt-1 flex justify-between gap-4 border-t border-slate-200 pt-1 dark:border-slate-700"><span>Neto</span><span className="num font-semibold">{soles(fila.Ingresos - fila.Gastos)}</span></div>}
    </div>
  );
}

function Anillo({ titulo, datos }) {
  const total = datos.reduce((a, d) => a + d.value, 0);
  return (
    <section className="card">
      <h2 className="mb-2 text-sm font-bold">{titulo}</h2>
      {total === 0 ? <p className="py-10 text-center text-sm text-slate-500">Sin movimientos en este periodo.</p> : (
        <>
          <div className="relative h-44">
            <ResponsiveContainer><PieChart>
              <Pie data={datos} dataKey="value" nameKey="name" innerRadius={52} outerRadius={78} paddingAngle={2} stroke="none" isAnimationActive={false}>
                {datos.map((_, i) => <Cell key={i} fill={PALETA[i % PALETA.length]} />)}
              </Pie>
              <Tooltip formatter={(v, n) => [soles(v), n]} contentStyle={{ borderRadius: 12, fontSize: 12 }} />
            </PieChart></ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 grid place-items-center text-center leading-tight"><div><b className="num block text-base font-extrabold">{solesCorto(total)}</b><span className="text-[11px] text-slate-500">total</span></div></div>
          </div>
          <ul className="mt-2 space-y-1.5 text-xs">
            {datos.map((d, i) => (
              <li key={d.name} className="flex items-center gap-2"><i className="h-2.5 w-2.5 flex-none rounded-sm" style={{ background: PALETA[i % PALETA.length] }} />
                <span className="min-w-0 flex-1 truncate text-slate-600 dark:text-slate-300">{d.name}</span>
                <span className="num font-semibold">{soles(d.value, 0)}</span><span className="num w-9 text-right text-slate-500">{Math.round((d.value / total) * 100)}%</span></li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
