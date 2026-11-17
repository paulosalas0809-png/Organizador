// Utilidades compartidas: moneda, fechas y catálogos del colegio.
export const soles = (n, dec = 2) =>
  `${n < 0 ? "−" : ""}S/ ${Math.abs(Number(n) || 0).toLocaleString("es-PE", { minimumFractionDigits: dec, maximumFractionDigits: dec })}`;
export const solesCorto = (n) => (Math.abs(n) >= 1000 ? `S/ ${(n / 1000).toFixed(Math.abs(n) >= 10000 ? 0 : 1)}k` : `S/ ${Math.round(n)}`);

export const MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Setiembre", "Octubre", "Noviembre", "Diciembre"];
export const CATEGORIAS = {
  ingreso: ["Pensiones", "Matrículas", "Venta de Uniformes/Libros", "Certificados/Trámites", "Eventos/Otros"],
  gasto: ["Planilla Docente/Administrativa", "Mantenimiento e Infraestructura", "Servicios Básicos (Luz/Agua/Internet)", "Materiales Educativos", "Caja Chica/Otros"],
};
export const METODOS = ["Efectivo", "Yape / Plin", "Transferencia Bancaria", "Tarjeta"];
export const PERMISOS = { ambos: "Ambos", ingresos: "Solo Ingresos", gastos: "Solo Gastos" };
export const SYNC = {
  ok: { texto: "En Excel", clase: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" },
  pendiente: { texto: "Enviando", clase: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300" },
  error: { texto: "Falló el envío", clase: "bg-coral-100 text-coral-700 dark:bg-coral-500/15 dark:text-coral-400" },
  sin_enlace: { texto: "Sin enlace", clase: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" },
  excel: { texto: "Leído de Excel", clase: "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300" },
  ejemplo: { texto: "Ejemplo", clase: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400" },
};

const pad = (n) => String(n).padStart(2, "0");
export const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const fecha = (s) => new Date(`${s}T12:00:00`);
export const masDias = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
export const lunesDe = (d) => masDias(d, -((d.getDay() + 6) % 7));
export const fechaCorta = (s) => fecha(s).toLocaleDateString("es-PE", { day: "numeric", month: "short" });

export function semanaISO(d) {
  const x = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dia = x.getUTCDay() || 7;
  x.setUTCDate(x.getUTCDate() + 4 - dia);
  return Math.ceil(((x - Date.UTC(x.getUTCFullYear(), 0, 1)) / 864e5 + 1) / 7);
}

export const suma = (xs, tipo) => xs.reduce((a, t) => a + (!tipo || t.tipo === tipo ? t.monto : 0), 0);
export const entre = (tx, desde, hasta) => tx.filter((t) => t.fecha >= desde && t.fecha <= hasta);
export const variacion = (ahora, antes) => (antes > 0 ? ((ahora - antes) / antes) * 100 : null);
