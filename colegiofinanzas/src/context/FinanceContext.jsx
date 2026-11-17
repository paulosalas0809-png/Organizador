import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../services/api.js";
import { resumenCola, seguirEnvio, sincronizarPendientes } from "../services/excelSync.js";

// Estado global de la app. La fuente de verdad vive en el servidor: aquí se guarda la copia en
// memoria de lo que cada entorno tiene permitido ver.
//   · Dirección: movimientos, personal autorizado, enlace de Excel y cola de sincronización.
//   · Mini-App:  solo el perfil que entró y sus últimos 5 registros del día.
const Ctx = createContext(null);
export const useFinance = () => useContext(Ctx);

export function FinanceProvider({ children }) {
  const [admin, setAdmin] = useState({ listo: false, autenticado: false });
  const [datos, setDatos] = useState(null);                  // estado completo (solo Dirección)
  const [caja, setCaja] = useState({ listo: false, usuario: null, recientes: [], perfiles: [], bloqueado: false, colegio: "" });
  const [aviso, setAviso] = useState(null);
  const temporizador = useRef();

  const avisar = useCallback((texto, tipo = "ok") => {
    setAviso({ texto, tipo });
    clearTimeout(temporizador.current);
    temporizador.current = setTimeout(() => setAviso(null), 3500);
  }, []);

  // ------------------------------------------------------------ Dirección
  const cargarAdmin = useCallback(async () => {
    try {
      setDatos(await api("/admin/datos"));
      setAdmin({ listo: true, autenticado: true });
      return true;
    } catch (e) {
      if (e.estado === 401) { setAdmin({ listo: true, autenticado: false }); setDatos(null); }
      return false;
    }
  }, []);

  const entrarAdmin = useCallback(async (pin) => { await api("/admin/entrar", { metodo: "POST", cuerpo: { pin } }); await cargarAdmin(); }, [cargarAdmin]);
  const salirAdmin = useCallback(async () => { await api("/admin/salir", { metodo: "POST" }); setDatos(null); setAdmin({ listo: true, autenticado: false }); }, []);

  // Toda operación de Dirección devuelve el estado actualizado
  const operar = useCallback(async (ruta, metodo, cuerpo, mensaje) => {
    try {
      const nuevo = await api(ruta, { metodo, cuerpo });
      if (nuevo.tx) setDatos(nuevo);
      if (mensaje) avisar(mensaje);
      return nuevo;
    } catch (e) {
      if (e.estado === 401) setAdmin({ listo: true, autenticado: false });
      avisar(e.message, "error");
      throw e;
    }
  }, [avisar]);

  const acciones = useMemo(() => ({
    guardarConfig: (c, m = "Cambios guardados") => operar("/admin/config", "POST", c, m),
    crearUsuario: (u) => operar("/admin/usuarios", "POST", u, "Persona autorizada"),
    editarUsuario: (id, u, m = "Acceso actualizado") => operar(`/admin/usuarios/${id}`, "PUT", u, m),
    borrarUsuario: (id) => operar(`/admin/usuarios/${id}`, "DELETE", undefined, "Acceso eliminado"),
    editarTx: (id, t) => operar(`/admin/tx/${id}`, "PUT", t, "Registro corregido"),
    borrarTx: (id) => operar(`/admin/tx/${id}`, "DELETE", undefined, "Registro eliminado"),
    limpiarEjemplo: () => operar("/admin/limpiar-ejemplo", "POST", {}, "Datos de ejemplo eliminados"),
    sincronizar: async () => {
      const r = await operar("/admin/sync/pendientes", "POST", {});
      await cargarAdmin();
      avisar(r.fallidos ? `${r.enviados} enviados, ${r.fallidos} fallaron` : `${r.enviados} registros enviados a Excel`, r.fallidos ? "error" : "ok");
      return r;
    },
  }), [operar, cargarAdmin, avisar]);

  // Refresco periódico: los registros que hace el personal aparecen solos en el tablero
  useEffect(() => {
    if (!admin.autenticado) return;
    const t = setInterval(() => { if (!document.hidden) cargarAdmin(); }, 20000);
    return () => clearInterval(t);
  }, [admin.autenticado, cargarAdmin]);

  // ------------------------------------------------------------ Mini-App
  const cargarCaja = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([api("/caja/sesion"), api("/caja/perfiles")]);
      // «bloqueado» se conserva hasta que la persona vuelva a entrar: así ve por qué salió
      setCaja((c) => ({ listo: true, usuario: s.usuario, recientes: s.recientes || [], bloqueado: !s.usuario && (!!s.bloqueado || c.bloqueado), perfiles: p.perfiles, colegio: p.colegio }));
      return s.recientes || [];
    } catch (e) {
      setCaja((c) => ({ ...c, listo: true }));
      return [];
    }
  }, []);

  const entrarCaja = useCallback(async (pin, userId) => {
    const r = await api("/caja/entrar", { metodo: "POST", cuerpo: { pin, userId } });
    setCaja((c) => ({ ...c, usuario: r.usuario, bloqueado: false }));
    await cargarCaja();
  }, [cargarCaja]);

  const salirCaja = useCallback(async () => { await api("/caja/salir", { metodo: "POST" }); await cargarCaja(); }, [cargarCaja]);

  const registrar = useCallback(async (mov) => {
    try {
      const r = await api("/caja/registrar", { metodo: "POST", cuerpo: mov });
      setCaja((c) => ({ ...c, recientes: r.recientes }));
      // Doble envío: ya está en el sistema; ahora se sigue su llegada al Excel
      seguirEnvio(cargarCaja).then(() => { if (admin.autenticado) cargarAdmin(); });
      return r;
    } catch (e) {
      if (e.datos?.bloqueado) { setCaja((c) => ({ ...c, usuario: null, recientes: [], bloqueado: true })); cargarCaja(); }
      throw e;
    }
  }, [cargarCaja, cargarAdmin, admin.autenticado]);

  const valor = useMemo(() => ({
    admin, datos, cola: resumenCola(datos?.tx), aviso, avisar,
    cargarAdmin, entrarAdmin, salirAdmin, ...acciones,
    caja, cargarCaja, entrarCaja, salirCaja, registrar, sincronizarPendientes,
  }), [admin, datos, aviso, avisar, cargarAdmin, entrarAdmin, salirAdmin, acciones, caja, cargarCaja, entrarCaja, salirCaja, registrar]);

  return <Ctx.Provider value={valor}>{children}</Ctx.Provider>;
}
