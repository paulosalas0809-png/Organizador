// Cliente del backend de ColegioFinanzas OS (mismo servidor, cookies de sesión).
export class ErrorApi extends Error {
  constructor(mensaje, estado, datos) { super(mensaje); this.estado = estado; this.datos = datos || {}; }
}

export async function api(ruta, { metodo = "GET", cuerpo } = {}) {
  let r;
  try {
    r = await fetch(`/api/colegio${ruta}`, {
      method: metodo, credentials: "same-origin",
      headers: cuerpo === undefined ? undefined : { "Content-Type": "application/json" },
      body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
    });
  } catch (e) {
    throw new ErrorApi("Sin conexión con el servidor. Revisa tu internet.", 0);
  }
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new ErrorApi(datos.error || datos.mensaje || "Algo salió mal.", r.status, datos);
  return datos;
}
