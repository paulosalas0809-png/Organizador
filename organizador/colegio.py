"""ColegioFinanzas OS — backend.

Guarda los movimientos del colegio, valida en el servidor los PIN, permisos y topes del
personal, y reenvía cada movimiento al Excel / Google Sheets configurado. Así la Mini-App
del personal nunca recibe las finanzas globales ni el enlace del Excel.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import random
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, timedelta
from functools import wraps
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request, session

from .config import cargar_config

bp = Blueprint("colegio", __name__, url_prefix="/api/colegio")
ZONA = ZoneInfo("America/Lima")
ARCHIVO = cargar_config().carpeta_datos / "colegio.json"
_candado = threading.RLock()

CATEGORIAS = {
    "ingreso": ["Pensiones", "Matrículas", "Venta de Uniformes/Libros", "Certificados/Trámites", "Eventos/Otros"],
    "gasto": ["Planilla Docente/Administrativa", "Mantenimiento e Infraestructura",
              "Servicios Básicos (Luz/Agua/Internet)", "Materiales Educativos", "Caja Chica/Otros"],
}
METODOS = ["Efectivo", "Yape / Plin", "Transferencia Bancaria", "Tarjeta"]
PERMISOS = ["ambos", "ingresos", "gastos"]
COLUMNAS = ["id", "fecha", "hora", "semana", "mes", "tipo", "categoria", "concepto", "monto", "metodoPago", "registradoPor"]
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Setiembre", "Octubre", "Noviembre", "Diciembre"]


# ---------------------------------------------------------------- almacenamiento


def _id() -> str:
    return uuid.uuid4().hex[:10]


def _sello(momento: datetime) -> dict:
    return {
        "fecha": momento.strftime("%Y-%m-%d"),
        "hora": momento.strftime("%H:%M:%S"),
        "semana": momento.isocalendar().week,
        "mes": MESES[momento.month - 1],
    }


def _ejemplo() -> dict:
    """Movimientos realistas de un colegio pequeño, de enero a hoy, para ver los gráficos poblados."""
    azar = random.Random(2026)
    hoy = datetime.now(ZONA).date()
    usuarios = [
        {"id": _id(), "nombre": "Ana", "cargo": "Secretaría", "pin": "1111", "permiso": "ambos", "tope": 2000, "activo": True, "demo": True},
        {"id": _id(), "nombre": "Carlos", "cargo": "Tesorería", "pin": "2222", "permiso": "ambos", "tope": 20000, "activo": True, "demo": True},
        {"id": _id(), "nombre": "Rosa", "cargo": "Caja", "pin": "3333", "permiso": "ingresos", "tope": 1000, "activo": True, "demo": True},
    ]
    grados = ["Inicial 5 años", "1.º primaria", "2.º primaria", "3.º primaria", "4.º primaria", "5.º primaria",
              "6.º primaria", "1.º secundaria", "2.º secundaria", "3.º secundaria"]
    tx = []

    def poner(dia, tipo, categoria, concepto, monto, metodo, quien=None, hora=None):
        u = quien or azar.choice(usuarios[:2] if tipo == "gasto" else usuarios)
        momento = datetime(dia.year, dia.month, dia.day, hora or azar.randint(8, 16), azar.randint(0, 59), azar.randint(0, 59), tzinfo=ZONA)
        tx.append({"id": _id(), **_sello(momento), "tipo": tipo, "categoria": categoria, "concepto": concepto,
                   "monto": round(monto, 2), "metodoPago": metodo, "nOperacion": f"B001-{len(tx) + 1:05d}",
                   "registradoPor": f"{u['cargo']} - {u['nombre']}", "userId": u["id"], "sync": "ejemplo", "demo": True})

    def metodo_ingreso():
        return azar.choices(METODOS, weights=[30, 40, 22, 8])[0]

    dia = date(hoy.year, 1, 5)
    while dia <= hoy:
        if dia.weekday() < 5:
            mes = MESES[dia.month - 1].lower()
            for _ in range(azar.choices([1, 2, 3], weights=[45, 40, 15])[0] if dia.month >= 3 else azar.randint(0, 1)):
                poner(dia, "ingreso", "Pensiones", f"Pensión {mes} – {azar.choice(grados)} (cód. A-{azar.randint(100, 399)})",
                      azar.choice([380, 380, 420, 420, 450]), metodo_ingreso())
            if dia.month <= 3 and azar.random() < .55:
                poner(dia, "ingreso", "Matrículas", f"Matrícula {hoy.year} – {azar.choice(grados)}", 300, metodo_ingreso())
            if dia.month in (2, 3, 4) and azar.random() < .3:
                poner(dia, "ingreso", "Venta de Uniformes/Libros", azar.choice(["Uniforme completo", "Buzo deportivo", "Pack de libros"]),
                      azar.choice([85, 120, 160, 210]), metodo_ingreso())
            if azar.random() < .12:
                poner(dia, "ingreso", "Certificados/Trámites", azar.choice(["Certificado de estudios", "Constancia de matrícula", "Duplicado de libreta"]),
                      azar.choice([25, 30, 50]), "Efectivo", usuarios[0])
            if azar.random() < .04:
                poner(dia, "ingreso", "Eventos/Otros", azar.choice(["Kermés – venta de tickets", "Alquiler de cafetín", "Taller de verano"]),
                      azar.choice([180, 350, 600]), metodo_ingreso())
            if azar.random() < .2:
                poner(dia, "gasto", "Caja Chica/Otros", azar.choice(["Movilidad", "Útiles de limpieza", "Fotocopias", "Agua de mesa"]),
                      azar.choice([18, 25, 40, 65, 90]), "Efectivo", usuarios[0])
            if azar.random() < .09:
                poner(dia, "gasto", "Materiales Educativos", azar.choice(["Plumones y papelógrafos", "Material de laboratorio", "Libros de biblioteca"]),
                      azar.choice([120, 180, 260, 340]), azar.choice(["Efectivo", "Transferencia Bancaria"]), usuarios[1])
            if azar.random() < .07:
                poner(dia, "gasto", "Mantenimiento e Infraestructura", azar.choice(["Gasfitería baños", "Pintura de aulas", "Reparación de carpetas", "Mantenimiento de cómputo"]),
                      azar.choice([150, 280, 450, 800]), azar.choice(["Efectivo", "Yape / Plin", "Transferencia Bancaria"]), usuarios[1])
            if dia.day in (9, 10, 11) and not any(t["fecha"][:7] == dia.strftime("%Y-%m") and "Luz" in t["concepto"] for t in tx):
                poner(dia, "gasto", "Servicios Básicos (Luz/Agua/Internet)", "Luz del Sur – recibo mensual", azar.randint(290, 360), "Transferencia Bancaria", usuarios[1])
                poner(dia, "gasto", "Servicios Básicos (Luz/Agua/Internet)", "Sedapal – recibo mensual", azar.randint(140, 190), "Transferencia Bancaria", usuarios[1])
                poner(dia, "gasto", "Servicios Básicos (Luz/Agua/Internet)", "Internet fibra 200 Mbps", 159.9, "Tarjeta", usuarios[1])
            if dia.day in (28, 29, 30) and not any(t["fecha"][:7] == dia.strftime("%Y-%m") and "Planilla docente" in t["concepto"] for t in tx):
                poner(dia, "gasto", "Planilla Docente/Administrativa", f"Planilla docente – {mes}", azar.randint(7600, 8200), "Transferencia Bancaria", usuarios[1])
                poner(dia, "gasto", "Planilla Docente/Administrativa", f"Planilla administrativa – {mes}", azar.randint(2300, 2600), "Transferencia Bancaria", usuarios[1])
        dia += timedelta(days=1)
    tx.sort(key=lambda t: (t["fecha"], t["hora"]))
    return {"config": {"adminPin": "0000", "webhook": "", "metaMensual": 16000, "colegio": "Mi Colegio"},
            "usuarios": usuarios, "tx": tx, "demo": True}


def _cargar() -> dict:
    with _candado:
        if ARCHIVO.exists():
            return json.loads(ARCHIVO.read_text(encoding="utf-8"))
        datos = _ejemplo()
        _guardar(datos)
        return datos


def _guardar(datos: dict) -> None:
    with _candado:
        ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
        temporal = ARCHIVO.with_suffix(".tmp")
        temporal.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        temporal.replace(ARCHIVO)


# ---------------------------------------------------------------- seguridad

_intentos: dict[str, list] = {}          # ip -> [fallos, bloqueado_hasta]


def _bloqueado(clave: str) -> int:
    fallos, hasta = _intentos.get(clave, [0, 0])
    return max(0, int(hasta - time.time()))


def _fallo(clave: str) -> None:
    fallos, _ = _intentos.get(clave, [0, 0])
    fallos += 1
    _intentos[clave] = [fallos, time.time() + (60 * min(15, 2 ** (fallos - 5)) if fallos >= 5 else 0)]


def _ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()


def admin(f):
    @wraps(f)
    def envoltura(*a, **kw):
        if not session.get("cf_admin"):
            return jsonify(error="Ingresa el PIN de Dirección."), 401
        return f(*a, **kw)
    return envoltura


def _usuario_activo(datos: dict):
    """El usuario de la sesión de la Mini-App, solo si sigue autorizado (se revisa en cada petición)."""
    u = next((x for x in datos["usuarios"] if x["id"] == session.get("cf_user")), None)
    return u if u and u.get("activo") else None


def _publico(u: dict) -> dict:
    return {"id": u["id"], "nombre": u["nombre"], "cargo": u["cargo"], "permiso": u["permiso"], "tope": u["tope"]}


# ---------------------------------------------------------------- envío a Excel / Sheets


def _url_segura(url: str) -> str | None:
    """Solo https hacia servidores públicos (evita que el enlace apunte a la red interna)."""
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname:
        return "El enlace debe empezar con https://"
    try:
        for info in socket.getaddrinfo(p.hostname, 443):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return "Ese enlace no apunta a un servicio público."
    except socket.gaierror:
        return "No encontré ese servidor. Revisa el enlace."
    return None


def _fila(tx: dict, accion: str) -> dict:
    fila = {c: tx.get(c, "") for c in COLUMNAS}
    fila.update(accion=accion, nOperacion=tx.get("nOperacion", ""))
    return fila


def _enviar(url: str, cuerpo: dict) -> tuple[bool, str]:
    problema = _url_segura(url)
    if problema:
        return False, problema
    pedido = urllib.request.Request(url, data=json.dumps(cuerpo, ensure_ascii=False).encode("utf-8"),
                                    headers={"Content-Type": "application/json", "User-Agent": "ColegioFinanzasOS/1.0"}, method="POST")
    try:
        with urllib.request.urlopen(pedido, timeout=20) as r:
            texto = r.read(2000).decode("utf-8", "replace")
            if "<html" in texto.lower() and "accounts.google" in texto.lower():
                return False, "Google pide iniciar sesión: publica el script con acceso «Cualquier usuario»."
            return True, "Recibido por la hoja"
    except urllib.error.HTTPError as e:
        return False, f"La hoja respondió con error {e.code}"
    except Exception as e:  # red, tiempo de espera, certificado…
        return False, f"No se pudo conectar: {type(e).__name__}"


def _sincronizar(tx_id: str, accion: str = "crear", intentos: int = 3) -> None:
    """Envía un movimiento con reintentos (0 s, 3 s, 9 s) y deja anotado el resultado."""
    for n in range(intentos):
        datos = _cargar()
        url = datos["config"].get("webhook", "")
        tx = next((t for t in datos["tx"] if t["id"] == tx_id), None)
        if not url or tx is None:
            return
        ok, mensaje = _enviar(url, _fila(tx, accion))
        with _candado:
            datos = _cargar()
            actual = next((t for t in datos["tx"] if t["id"] == tx_id), None)
            if actual is None:
                return
            actual["sync"], actual["syncMsg"] = ("ok" if ok else "error"), mensaje
            actual["syncAccion"] = accion
            _guardar(datos)
        if ok:
            return
        time.sleep(3 * 3 ** n)


def _en_segundo_plano(tx_id: str, accion: str) -> None:
    threading.Thread(target=_sincronizar, args=(tx_id, accion), daemon=True).start()


# ---------------------------------------------------------------- validación de movimientos


def _validar(d: dict, base: dict | None = None) -> tuple[dict | None, str | None]:
    tipo = str(d.get("tipo", (base or {}).get("tipo", ""))).lower()
    if tipo not in CATEGORIAS:
        return None, "Elige si es ingreso o gasto."
    categoria = str(d.get("categoria", (base or {}).get("categoria", "")))
    if categoria not in CATEGORIAS[tipo]:
        return None, "Elige una categoría."
    metodo = str(d.get("metodoPago", (base or {}).get("metodoPago", "")))
    if metodo not in METODOS:
        return None, "Elige el método de pago."
    try:
        monto = round(float(d.get("monto", (base or {}).get("monto", 0))), 2)
    except (TypeError, ValueError):
        return None, "El monto no es válido."
    if not 0 < monto <= 1_000_000:
        return None, "Escribe un monto mayor que cero."
    return {"tipo": tipo, "categoria": categoria, "metodoPago": metodo, "monto": monto,
            "concepto": str(d.get("concepto", (base or {}).get("concepto", ""))).strip()[:120],
            "nOperacion": str(d.get("nOperacion", (base or {}).get("nOperacion", ""))).strip()[:40]}, None


# ================================================================ Mini-App (personal)


@bp.get("/ping")
def ping():
    return jsonify(ok=True, admin=bool(session.get("cf_admin")))


@bp.get("/caja/perfiles")
def caja_perfiles():
    datos = _cargar()
    return jsonify(perfiles=[{"id": u["id"], "nombre": u["nombre"], "cargo": u["cargo"]} for u in datos["usuarios"] if u.get("activo")],
                   colegio=datos["config"].get("colegio", ""), categorias=CATEGORIAS, metodos=METODOS)


@bp.post("/caja/entrar")
def caja_entrar():
    clave = "caja:" + _ip()
    if _bloqueado(clave):
        return jsonify(error=f"Demasiados intentos. Espera {_bloqueado(clave) // 60 + 1} min."), 429
    d = request.json or {}
    pin = str(d.get("pin", ""))
    datos = _cargar()
    candidatos = [u for u in datos["usuarios"] if not d.get("userId") or u["id"] == d.get("userId")]
    u = next((x for x in candidatos if hmac.compare_digest(x["pin"], pin)), None)
    if u is None:
        _fallo(clave)
        return jsonify(error="PIN incorrecto."), 401
    if not u.get("activo"):
        return jsonify(error="Tu acceso está bloqueado. Consulta con Dirección."), 403
    _intentos.pop(clave, None)
    session.permanent = True
    session["cf_user"] = u["id"]
    return jsonify(usuario=_publico(u))


@bp.post("/caja/salir")
def caja_salir():
    session.pop("cf_user", None)
    return jsonify(ok=True)


def _mios(datos: dict, u: dict) -> list[dict]:
    """Solo los últimos 5 registros de hoy de ese usuario: nunca totales del colegio."""
    hoy = datetime.now(ZONA).strftime("%Y-%m-%d")
    mios = [t for t in datos["tx"] if t.get("userId") == u["id"] and t["fecha"] == hoy]
    campos = ("id", "hora", "tipo", "categoria", "concepto", "monto", "metodoPago", "sync")
    return [{k: t.get(k) for k in campos} for t in sorted(mios, key=lambda t: t["hora"], reverse=True)[:5]]


@bp.get("/caja/sesion")
def caja_sesion():
    datos = _cargar()
    u = _usuario_activo(datos)
    if u is None:
        bloqueado = any(x["id"] == session.get("cf_user") for x in datos["usuarios"])
        session.pop("cf_user", None)
        return jsonify(usuario=None, bloqueado=bloqueado)
    return jsonify(usuario=_publico(u), recientes=_mios(datos, u))


@bp.post("/caja/registrar")
def caja_registrar():
    with _candado:
        datos = _cargar()
        u = _usuario_activo(datos)
        if u is None:
            session.pop("cf_user", None)
            return jsonify(error="Tu acceso está bloqueado o tu sesión terminó.", bloqueado=True), 403
        campos, error = _validar(request.json or {})
        if error:
            return jsonify(error=error), 400
        if u["permiso"] == "ingresos" and campos["tipo"] != "ingreso":
            return jsonify(error="Tu acceso solo permite registrar ingresos."), 403
        if u["permiso"] == "gastos" and campos["tipo"] != "gasto":
            return jsonify(error="Tu acceso solo permite registrar gastos."), 403
        if u.get("tope") and campos["monto"] > float(u["tope"]):
            return jsonify(error=f"Tu tope por operación es S/ {float(u['tope']):,.2f}. Pide a Dirección que lo registre."), 403
        tx = {"id": _id(), **_sello(datetime.now(ZONA)), **campos, "registradoPor": f"{u['cargo']} - {u['nombre']}",
              "userId": u["id"], "sync": "pendiente" if datos["config"].get("webhook") else "sin_enlace"}
        datos["tx"].append(tx)
        _guardar(datos)
    if datos["config"].get("webhook"):
        _en_segundo_plano(tx["id"], "crear")
    return jsonify(ok=True, recientes=_mios(datos, u))


# ================================================================ Dirección


@bp.post("/admin/entrar")
def admin_entrar():
    clave = "admin:" + _ip()
    if _bloqueado(clave):
        return jsonify(error=f"Demasiados intentos. Espera {_bloqueado(clave) // 60 + 1} min."), 429
    datos = _cargar()
    if not hmac.compare_digest(datos["config"]["adminPin"], str((request.json or {}).get("pin", ""))):
        _fallo(clave)
        return jsonify(error="PIN incorrecto."), 401
    _intentos.pop(clave, None)
    session.permanent = True
    session["cf_admin"] = True
    return jsonify(ok=True)


@bp.post("/admin/salir")
def admin_salir():
    session.pop("cf_admin", None)
    return jsonify(ok=True)


def _estado(datos: dict):
    c = datos["config"]
    return jsonify(config={"webhook": c.get("webhook", ""), "metaMensual": c.get("metaMensual", 0), "colegio": c.get("colegio", "")},
                   pinPorDefecto=c["adminPin"] == "0000", usuarios=datos["usuarios"], tx=datos["tx"], demo=bool(datos.get("demo")),
                   categorias=CATEGORIAS, metodos=METODOS, hoy=datetime.now(ZONA).strftime("%Y-%m-%d"))


@bp.get("/admin/datos")
@admin
def admin_datos():
    return _estado(_cargar())


@bp.post("/admin/config")
@admin
def admin_config():
    d = request.json or {}
    with _candado:
        datos = _cargar()
        c = datos["config"]
        if "pinNuevo" in d:
            pin = str(d["pinNuevo"])
            if not (pin.isdigit() and len(pin) == 4):
                return jsonify(error="El PIN debe tener 4 dígitos."), 400
            c["adminPin"] = pin
        if "webhook" in d:
            url = str(d["webhook"]).strip()
            if url and _url_segura(url):
                return jsonify(error=_url_segura(url)), 400
            c["webhook"] = url
        if "metaMensual" in d:
            c["metaMensual"] = max(0, float(d["metaMensual"] or 0))
        if "colegio" in d:
            c["colegio"] = str(d["colegio"]).strip()[:60]
        _guardar(datos)
    return _estado(datos)


def _datos_usuario(d: dict, datos: dict, propio: str | None = None):
    nombre, cargo, pin = str(d.get("nombre", "")).strip()[:40], str(d.get("cargo", "")).strip()[:40], str(d.get("pin", ""))
    if not nombre:
        return None, "Escribe el nombre."
    if not (pin.isdigit() and len(pin) == 4):
        return None, "El PIN debe tener 4 dígitos."
    if any(u["pin"] == pin and u["id"] != propio for u in datos["usuarios"]):
        return None, "Ese PIN ya lo usa otra persona."
    permiso = d.get("permiso") if d.get("permiso") in PERMISOS else "ambos"
    try:
        tope = max(0, float(d.get("tope") or 0))
    except (TypeError, ValueError):
        return None, "El tope no es válido."
    return {"nombre": nombre, "cargo": cargo, "pin": pin, "permiso": permiso, "tope": tope, "activo": bool(d.get("activo", True))}, None


@bp.post("/admin/usuarios")
@admin
def admin_usuario_nuevo():
    with _candado:
        datos = _cargar()
        campos, error = _datos_usuario(request.json or {}, datos)
        if error:
            return jsonify(error=error), 400
        datos["usuarios"].append({"id": _id(), **campos})
        _guardar(datos)
    return _estado(datos)


@bp.put("/admin/usuarios/<uid>")
@admin
def admin_usuario_editar(uid):
    with _candado:
        datos = _cargar()
        u = next((x for x in datos["usuarios"] if x["id"] == uid), None)
        if u is None:
            return jsonify(error="Esa persona ya no existe."), 404
        d = request.json or {}
        if set(d) == {"activo"}:                       # interruptor Activar / Bloquear
            u["activo"] = bool(d["activo"])
        else:
            campos, error = _datos_usuario({**u, **d}, datos, propio=uid)
            if error:
                return jsonify(error=error), 400
            u.update(campos)
        _guardar(datos)
    return _estado(datos)


@bp.delete("/admin/usuarios/<uid>")
@admin
def admin_usuario_borrar(uid):
    with _candado:
        datos = _cargar()
        datos["usuarios"] = [u for u in datos["usuarios"] if u["id"] != uid]
        _guardar(datos)
    return _estado(datos)


@bp.put("/admin/tx/<tid>")
@admin
def admin_tx_editar(tid):
    with _candado:
        datos = _cargar()
        tx = next((t for t in datos["tx"] if t["id"] == tid), None)
        if tx is None:
            return jsonify(error="Ese registro ya no existe."), 404
        d = request.json or {}
        campos, error = _validar(d, base=tx)
        if error:
            return jsonify(error=error), 400
        tx.update(campos)
        if d.get("fecha"):
            try:
                dia = datetime.strptime(d["fecha"], "%Y-%m-%d")
                tx.update(fecha=d["fecha"], semana=dia.isocalendar().week, mes=MESES[dia.month - 1])
            except ValueError:
                return jsonify(error="La fecha no es válida."), 400
        tx["editado"] = datetime.now(ZONA).strftime("%Y-%m-%d %H:%M")
        enviar = bool(datos["config"].get("webhook")) and tx.get("sync") != "ejemplo"
        if enviar:
            tx["sync"] = "pendiente"
        _guardar(datos)
    if enviar:
        _en_segundo_plano(tid, "actualizar")
    return _estado(datos)


@bp.delete("/admin/tx/<tid>")
@admin
def admin_tx_borrar(tid):
    with _candado:
        datos = _cargar()
        tx = next((t for t in datos["tx"] if t["id"] == tid), None)
        datos["tx"] = [t for t in datos["tx"] if t["id"] != tid]
        _guardar(datos)
    if tx and tx.get("sync") == "ok" and datos["config"].get("webhook"):
        threading.Thread(target=_enviar, args=(datos["config"]["webhook"], _fila(tx, "eliminar")), daemon=True).start()
    return _estado(datos)


@bp.post("/admin/limpiar-ejemplo")
@admin
def admin_limpiar():
    with _candado:
        datos = _cargar()
        datos["tx"] = [t for t in datos["tx"] if not t.get("demo")]
        datos["usuarios"] = [u for u in datos["usuarios"] if not u.get("demo")]
        datos["demo"] = False
        _guardar(datos)
    return _estado(datos)


@bp.post("/admin/sync/probar")
@admin
def admin_probar():
    datos = _cargar()
    url = str((request.json or {}).get("webhook") or datos["config"].get("webhook", "")).strip()
    if not url:
        return jsonify(error="Pega primero el enlace de tu Excel o Google Sheets."), 400
    prueba = {"id": "PRUEBA", **_sello(datetime.now(ZONA)), "tipo": "ingreso", "categoria": "Pensiones",
              "concepto": "Prueba de conexión – ColegioFinanzas OS", "monto": 1, "metodoPago": "Efectivo", "registradoPor": "Dirección"}
    ok, mensaje = _enviar(url, _fila(prueba, "prueba"))
    return jsonify(ok=ok, mensaje=mensaje, enviado=_fila(prueba, "prueba")), (200 if ok else 502)


@bp.post("/admin/sync/pendientes")
@admin
def admin_pendientes():
    datos = _cargar()
    if not datos["config"].get("webhook"):
        return jsonify(error="Pega primero el enlace de tu Excel o Google Sheets."), 400
    pendientes = [t["id"] for t in datos["tx"] if t.get("sync") in ("pendiente", "error", "sin_enlace")]
    for tid in pendientes[:300]:
        _sincronizar(tid, "crear", intentos=1)
    datos = _cargar()
    hechos = sum(1 for t in datos["tx"] if t["id"] in pendientes and t.get("sync") == "ok")
    return jsonify(enviados=hechos, fallidos=len(pendientes[:300]) - hechos, restantes=max(0, len(pendientes) - 300))
