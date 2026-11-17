import { useEffect, useState } from "react";
import { GraduationCap, LayoutDashboard, Lock, LogOut, Moon, Smartphone, Sun } from "lucide-react";
import { useFinance } from "./context/FinanceContext.jsx";
import MiniAppCaja from "./components/MiniAppCaja.jsx";
import AdminDashboard from "./components/AdminDashboard.jsx";

// Dos entornos separados por URL:
//   /colegio?view=caja  → solo la Mini-App de registro (personal autorizado)
//   /colegio            → Panel Directivo, protegido por el PIN de Dirección
const vistaInicial = () => (new URLSearchParams(window.location.search).get("view") === "caja" ? "caja" : "admin");

export default function App() {
  const { admin, cargarAdmin, aviso } = useFinance();
  const [vista, setVista] = useState(vistaInicial);
  const [oscuro, setOscuro] = useState(() => {
    try { const g = localStorage.getItem("cf-tema"); if (g) return g === "dark"; } catch (e) { /* sin almacenamiento */ }
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });
  // El enlace ?view=caja queda fijo en ese modo: no ofrece ningún camino hacia el panel
  const soloCaja = vistaInicial() === "caja";

  useEffect(() => {
    document.documentElement.classList.toggle("dark", oscuro);
    try { localStorage.setItem("cf-tema", oscuro ? "dark" : "light"); } catch (e) { /* sin almacenamiento */ }
  }, [oscuro]);
  useEffect(() => { if (!soloCaja) cargarAdmin(); }, [soloCaja, cargarAdmin]);

  const cambiar = (v) => {
    setVista(v);
    const url = new URL(window.location.href);
    if (v === "caja") url.searchParams.set("view", "preview"); else url.searchParams.delete("view");
    window.history.replaceState(null, "", url);
  };

  let contenido;
  if (soloCaja) contenido = <MiniAppCaja />;
  else if (!admin.listo) contenido = <p className="p-16 text-center text-sm text-slate-500">Cargando…</p>;
  else if (!admin.autenticado) contenido = <PinDireccion />;
  else contenido = (
    <>
      <BarraSuperior vista={vista} cambiar={cambiar} oscuro={oscuro} setOscuro={setOscuro} />
      {vista === "caja"
        ? <div className="mx-auto max-w-md px-3 py-4"><p className="mb-3 rounded-xl bg-amber-100 px-3 py-2 text-xs font-medium text-amber-800 dark:bg-amber-500/15 dark:text-amber-300">Vista de prueba: así ve la Mini-App tu personal.</p><MiniAppCaja incrustada /></div>
        : <AdminDashboard />}
    </>
  );

  return (
    <div className="min-h-full">
      {contenido}
      {aviso && (
        <div role="status" className={`fixed bottom-5 left-1/2 z-50 max-w-[calc(100%-2rem)] -translate-x-1/2 rounded-xl px-4 py-2.5 text-sm font-medium text-white shadow-lg ${aviso.tipo === "error" ? "bg-coral-600" : "bg-slate-900 dark:bg-slate-700"}`}>
          {aviso.texto}
        </div>
      )}
    </div>
  );
}

function BarraSuperior({ vista, cambiar, oscuro, setOscuro }) {
  const { salirAdmin, datos } = useFinance();
  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
      <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2.5">
        <div className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-indigo-600 text-white"><GraduationCap size={20} /></span>
          <div className="leading-tight">
            <b className="block text-sm font-bold tracking-tight">ColegioFinanzas OS</b>
            <span className="hidden text-xs text-slate-500 sm:block">{datos?.config.colegio || "Panel de Dirección"}</span>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-800">
          {[["admin", "Vista Directiva", LayoutDashboard], ["caja", "Vista Mini-App", Smartphone]].map(([v, texto, Icono]) => (
            <button key={v} onClick={() => cambiar(v)} className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition ${vista === v ? "bg-white text-slate-900 shadow-sm dark:bg-slate-600 dark:text-white" : "text-slate-500"}`}>
              <Icono size={15} /><span className="hidden sm:inline">{texto}</span>
            </button>
          ))}
        </div>
        <button onClick={() => setOscuro(!oscuro)} title="Cambiar tema" className="grid h-9 w-9 place-items-center rounded-xl text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">{oscuro ? <Sun size={17} /> : <Moon size={17} />}</button>
        <button onClick={salirAdmin} title="Cerrar sesión de Dirección" className="grid h-9 w-9 place-items-center rounded-xl text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"><LogOut size={17} /></button>
      </div>
    </header>
  );
}

function PinDireccion() {
  const { entrarAdmin } = useFinance();
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [cargando, setCargando] = useState(false);
  const enviar = async (e) => {
    e.preventDefault();
    setCargando(true); setError("");
    try { await entrarAdmin(pin); } catch (err) { setError(err.message); setPin(""); }
    setCargando(false);
  };
  return (
    <div className="grid min-h-screen place-items-center bg-slate-950 p-4">
      <form onSubmit={enviar} className="w-full max-w-sm rounded-3xl bg-white p-8 text-center shadow-2xl dark:bg-slate-900">
        <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-indigo-600 text-white"><Lock size={24} /></span>
        <h1 className="mt-4 text-xl font-bold tracking-tight">ColegioFinanzas OS</h1>
        <p className="mt-1 text-sm text-slate-500">Panel de Dirección · ingresa tu PIN maestro</p>
        <input autoFocus type="password" inputMode="numeric" maxLength={4} value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
          aria-label="PIN de Dirección" placeholder="••••" className="field mt-6 text-center text-2xl tracking-[0.6em]" />
        {error && <p className="mt-3 rounded-lg bg-coral-50 px-3 py-2 text-sm text-coral-700 dark:bg-coral-500/10 dark:text-coral-400">{error}</p>}
        <button className="btn mt-4 w-full" disabled={pin.length !== 4 || cargando}>{cargando ? "Verificando…" : "Entrar"}</button>
      </form>
    </div>
  );
}
