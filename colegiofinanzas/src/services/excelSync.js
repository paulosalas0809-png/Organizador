// Sincronización con el Excel / Google Sheets del colegio.
//
// Cada ingreso o gasto se envía por POST al enlace configurado (Google Apps Script o Power Automate).
// El envío lo hace el servidor, no el celular: así el enlace del Excel nunca llega al dispositivo del
// personal y funciona también con Power Automate, que rechaza peticiones directas desde un navegador.
// El servidor reintenta solo (0 s, 3 s y 9 s); este servicio dispara los envíos y sigue su estado.
import { api } from "./api.js";

export const COLUMNAS = ["id", "fecha", "hora", "semana", "mes", "tipo", "categoria", "concepto", "monto", "metodoPago", "registradoPor"];
const PENDIENTES = ["pendiente", "error", "sin_enlace"];

/** Resumen de la cola de sincronización a partir de los movimientos. */
export function resumenCola(tx = []) {
  const reales = tx.filter((t) => t.sync !== "ejemplo");
  return {
    total: reales.length,
    ok: reales.filter((t) => t.sync === "ok").length,
    enviando: reales.filter((t) => t.sync === "pendiente").length,
    fallidos: reales.filter((t) => t.sync === "error").length,
    sinEnlace: reales.filter((t) => t.sync === "sin_enlace").length,
    pendientes: reales.filter((t) => PENDIENTES.includes(t.sync)).length,
  };
}

/** Envía una fila de prueba con todas las columnas al enlace indicado (o al guardado). */
export async function probarConexion(webhook) {
  try {
    const r = await api("/admin/sync/probar", { metodo: "POST", cuerpo: { webhook } });
    return { ok: true, mensaje: r.mensaje, enviado: r.enviado };
  } catch (e) {
    return { ok: false, mensaje: e.message, enviado: e.datos?.enviado };
  }
}

/** Reenvía todo lo que no llegó (registros hechos sin enlace, o cuyo envío falló). */
export const sincronizarPendientes = () => api("/admin/sync/pendientes", { metodo: "POST" });

/**
 * Tras registrar un movimiento, vuelve a consultar hasta que deje de estar «Enviando».
 * `consultar` debe devolver la lista actual; se reintenta con esperas crecientes.
 */
export async function seguirEnvio(consultar, { intentos = 5, espera = 1500 } = {}) {
  for (let i = 0; i < intentos; i++) {
    await new Promise((ok) => setTimeout(ok, espera * (i + 1)));
    const lista = await consultar().catch(() => null);
    if (lista && !lista.some((t) => t.sync === "pendiente")) return lista;
  }
  return null;
}
