"""App web del Organizador: tu asistente de productividad, en el PC o en el celular.

Local:     py -m organizador.web          (abre http://localhost:8000)
Servidor:  gunicorn organizador.web:app
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
from datetime import date, datetime, timedelta
from functools import wraps

import anthropic
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.errors import HttpError
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import cargar_config
from .google_api import SCOPES, Google, Tarea, huecos_libres
from .agente import Agente, ErrorIA, Metas, gemini_disponible, motivacion_del_dia, plan_con_gemini
from .planificador import DIAS, construir_contexto, conversar, generar_plan, plan_sin_ia

EN_SERVIDOR = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("EN_SERVIDOR"))
if not EN_SERVIDOR:
    # En tu PC la app corre en http://localhost, sin https.
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

cfg = cargar_config()
cfg.carpeta_datos.mkdir(parents=True, exist_ok=True)
ARCHIVO_TOKEN = cfg.carpeta_datos / "google_token.json"
metas = Metas(cfg.carpeta_datos)

TIPOS_AGENDABLES = {"tarea", "enfoque", "rutina"}
ICONOS = {"tarea": "✅", "evento": "📅", "descanso": "☕", "enfoque": "🎯", "rutina": "🔁"}


def _clave_secreta() -> str:
    if os.getenv("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    archivo = cfg.carpeta_datos / "secret_key"
    if not archivo.exists():
        archivo.write_text(secrets.token_hex(32))
    return archivo.read_text().strip()


app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.update(
    SECRET_KEY=_clave_secreta(),
    PERMANENT_SESSION_LIFETIME=timedelta(days=90),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=EN_SERVIDOR,
    MAX_CONTENT_LENGTH=12 * 1024 * 1024,  # imágenes para el agente
)


# ---------------------------------------------------------------- utilidades


def ahora() -> datetime:
    return datetime.now(cfg.zona)


def claude_disponible() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def ia_disponible() -> bool:
    return gemini_disponible() or claude_disponible()


def config_cliente_google() -> dict | None:
    # .strip() por si al copiar quedaron espacios o saltos de línea invisibles
    cid = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    secreto = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if cid and secreto:
        return {
            "web": {
                "client_id": cid,
                "client_secret": secreto,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
    if cfg.archivo_credenciales.exists():
        datos = json.loads(cfg.archivo_credenciales.read_text())
        if "web" in datos:
            return datos
    return None


def credenciales_google() -> Credentials | None:
    if not ARCHIVO_TOKEN.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(ARCHIVO_TOKEN), SCOPES)
    if not creds.valid:
        if not (creds.expired and creds.refresh_token):
            return None
        try:
            creds.refresh(Request())
        except RefreshError:
            return None
        ARCHIVO_TOKEN.write_text(creds.to_json())
    return creds


def google() -> Google:
    creds = credenciales_google()
    if creds is None:
        raise PermissionError("google_desconectado")
    return Google(cfg, creds)


def ordenar(tareas: list[Tarea]) -> list[Tarea]:
    return sorted(tareas, key=lambda t: (t.vence is None, t.vence or date.max, t.titulo.lower()))


def archivo_plan(dia: date):
    return cfg.carpeta_datos / f"plan-{dia.isoformat()}.json"


def archivo_agenda(dia: date):
    return cfg.carpeta_datos / f"agenda-{dia.isoformat()}.json"


def agenda_cumplida(dia: date) -> set[str]:
    """Ids de los eventos de ese día que marcaste como cumplidos."""
    if archivo_agenda(dia).exists():
        return set(json.loads(archivo_agenda(dia).read_text()))
    return set()


def requiere_login(f):
    @wraps(f)
    def envoltura(*a, **kw):
        if not session.get("ok"):
            if request.path.startswith("/api/"):
                return jsonify(error="Sesión cerrada, vuelve a entrar."), 401
            return redirect(url_for("login"))
        try:
            return f(*a, **kw)
        except PermissionError:
            return jsonify(error="Conecta tu cuenta de Google.", google_desconectado=True), 409
        except HttpError as e:
            return jsonify(error=f"Google respondió con un error ({e.status_code})."), 502
        except anthropic.AuthenticationError:
            return jsonify(error="La clave de Claude (ANTHROPIC_API_KEY) no es válida."), 502
        except anthropic.RateLimitError:
            return jsonify(error="Claude está ocupado, intenta en un minuto."), 503
        except anthropic.APIStatusError as e:
            return jsonify(error=f"Error de Claude ({e.status_code})."), 502
        except anthropic.APIConnectionError:
            return jsonify(error="No pude conectarme con Claude."), 502
        except ErrorIA as e:
            return jsonify(error=str(e)), 503
        except RuntimeError as e:
            return jsonify(error=str(e)), 502

    return envoltura


def datos_del_dia(g: Google, dia):
    eventos = g.eventos_del_dia(dia)
    tareas = ordenar(g.tareas_pendientes())
    return eventos, tareas


# ---------------------------------------------------------------- login


@app.route("/entrar", methods=["GET", "POST"])
def login():
    clave = os.getenv("APP_PASSWORD", "").strip()
    error = None
    if not clave:
        error = "Falta configurar APP_PASSWORD en el servidor."
    elif request.method == "POST":
        if hmac.compare_digest(request.form.get("clave", "").strip(), clave):
            session.permanent = True
            session["ok"] = True
            return redirect(url_for("inicio"))
        error = "Contraseña incorrecta."
    return render_template("entrar.html", error=error)


@app.route("/salir")
def salir():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- Google OAuth


@app.route("/google/conectar")
@requiere_login
def google_conectar():
    cliente = config_cliente_google()
    if cliente is None:
        return "Faltan GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET en la configuración.", 500
    flow = Flow.from_client_config(cliente, SCOPES, redirect_uri=url_for("google_callback", _external=True))
    url, estado = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    session["oauth_estado"] = estado
    session["oauth_verificador"] = flow.code_verifier
    return redirect(url)


@app.route("/google/callback")
@requiere_login
def google_callback():
    cliente = config_cliente_google()
    flow = Flow.from_client_config(
        cliente,
        SCOPES,
        state=session.pop("oauth_estado", None),
        redirect_uri=url_for("google_callback", _external=True),
        code_verifier=session.pop("oauth_verificador", None),
        autogenerate_code_verifier=False,
    )
    try:
        flow.fetch_token(authorization_response=request.url)
    except Exception as e:  # errores de OAuth: secreto incorrecto, permiso cancelado, etc.
        app.logger.warning("Error conectando Google: %s", e)
        mensaje = str(e)
        if "client secret" in mensaje:
            mensaje = "El GOOGLE_CLIENT_SECRET no es correcto. Revísalo en Railway."
        elif "access_denied" in mensaje:
            mensaje = "Cancelaste el permiso o tu cuenta no está como usuario de prueba."
        return render_template("entrar.html", error=f"No pude conectar Google: {mensaje}"), 400
    ARCHIVO_TOKEN.write_text(flow.credentials.to_json())
    return redirect(url_for("inicio"))


# ---------------------------------------------------------------- páginas


@app.route("/")
@requiere_login
def inicio():
    return render_template("index.html")


@app.route("/manifest.webmanifest")
def manifest():
    return app.send_static_file("manifest.webmanifest")


# ---------------------------------------------------------------- API


@app.get("/api/hoy")
@requiere_login
def api_hoy():
    momento = ahora()
    dia = momento.date()
    base = {
        "fecha": f"{DIAS[dia.weekday()].capitalize()} {dia.day} de "
        + ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre"][dia.month - 1],
        "hora": momento.strftime("%H:%M"),
        "nombre": os.getenv("NOMBRE", "").strip(),
        "ia": ia_disponible(),
        "agente": gemini_disponible(),
        "google": False,
    }
    creds = credenciales_google()
    if creds is None:
        return jsonify(base)
    g = Google(cfg, creds)
    eventos, tareas = datos_del_dia(g, dia)
    completadas = g.tareas_completadas_hoy(dia)
    cumplidos = agenda_cumplida(dia)
    plan = None
    if archivo_plan(dia).exists():
        plan = json.loads(archivo_plan(dia).read_text())
    base.update(
        google=True,
        eventos=[
            {
                "id": e.id,
                "hecho": e.id in cumplidos,
                "titulo": e.titulo,
                "inicio": e.inicio.strftime("%H:%M"),
                "fin": e.fin.strftime("%H:%M"),
                "todo_el_dia": e.todo_el_dia,
                "organizador": e.creado_por_organizador,
                "calendario": e.calendario,
            }
            for e in eventos
        ],
        proximos=[
            {
                "titulo": e.titulo,
                "fecha": e.inicio.date().isoformat(),
                "hora": "" if e.todo_el_dia else e.inicio.strftime("%H:%M"),
                "dias": (e.inicio.date() - dia).days,
                "calendario": e.calendario,
            }
            for e in g.eventos_entre(dia + timedelta(days=1), dia + timedelta(days=31))
            if not e.creado_por_organizador
        ][:40],
        tareas=[
            {
                "id": t.id,
                "lista_id": t.lista_id,
                "titulo": t.titulo,
                "lista": t.lista,
                "notas": t.notas,
                "vence": t.vence.isoformat() if t.vence else None,
                "estado": (
                    "sin_fecha" if t.vence is None
                    else "vencida" if t.vence < dia
                    else "hoy" if t.vence == dia
                    else "futura"
                ),
            }
            for t in tareas
        ],
        completadas=completadas,
        plan=plan,
        metas=metas.listar(),
    )
    return jsonify(base)


@app.post("/api/plan")
@requiere_login
def api_plan():
    nota = (request.json or {}).get("nota", "")[:500]
    momento = ahora()
    dia = momento.date()
    g = google()
    eventos, tareas = datos_del_dia(g, dia)
    huecos = huecos_libres(eventos, dia, cfg, desde=momento)
    if gemini_disponible():
        contexto = construir_contexto(dia, momento, eventos, tareas, huecos, cfg, nota)
        plan = plan_con_gemini(contexto, metas.listar()).model_dump()
    elif claude_disponible():
        contexto = construir_contexto(dia, momento, eventos, tareas, huecos, cfg, nota)
        plan = generar_plan(contexto).model_dump()
    else:
        plan = plan_sin_ia(dia, eventos, tareas, huecos).model_dump()
    for b in plan["bloques"]:
        n = b.get("tarea_numero")
        if n and 1 <= n <= len(tareas):
            b["tarea_id"], b["lista_id"] = tareas[n - 1].id, tareas[n - 1].lista_id
    plan["otro_dia"] = [tareas[n - 1].titulo for n in plan.pop("tareas_para_otro_dia", []) if 1 <= n <= len(tareas)]
    plan["generado"] = momento.strftime("%H:%M")
    plan["agendado"] = False
    archivo_plan(dia).write_text(json.dumps(plan, ensure_ascii=False))
    return jsonify(plan)


@app.post("/api/agendar")
@requiere_login
def api_agendar():
    dia = ahora().date()
    if not archivo_plan(dia).exists():
        return jsonify(error="Primero genera tu plan."), 400
    plan = json.loads(archivo_plan(dia).read_text())
    g = google()
    g.borrar_bloques_del_organizador(dia)
    creados = 0
    for b in plan["bloques"]:
        if b["tipo"] not in TIPOS_AGENDABLES:
            continue
        try:
            ini = datetime.combine(dia, datetime.strptime(b["inicio"], "%H:%M").time(), cfg.zona)
            fin = datetime.combine(dia, datetime.strptime(b["fin"], "%H:%M").time(), cfg.zona)
        except ValueError:
            continue
        if fin <= ini:
            continue
        g.crear_bloque(f"{ICONOS.get(b['tipo'], '')} {b['titulo']}".strip(), ini, fin, b.get("nota", ""))
        creados += 1
    plan["agendado"] = True
    archivo_plan(dia).write_text(json.dumps(plan, ensure_ascii=False))
    return jsonify(creados=creados)


@app.post("/api/agenda/marcar")
@requiere_login
def api_agenda_marcar():
    datos = request.json or {}
    evento_id = str(datos.get("id") or "")[:300]
    if not evento_id:
        return jsonify(error="Falta el evento."), 400
    dia = ahora().date()
    cumplidos = agenda_cumplida(dia)
    if datos.get("hecho", True):
        cumplidos.add(evento_id)
    else:
        cumplidos.discard(evento_id)
    archivo_agenda(dia).write_text(json.dumps(sorted(cumplidos)))
    return jsonify(ok=True)


@app.post("/api/tareas/completar")
@requiere_login
def api_completar():
    datos = request.json or {}
    google().completar_tarea_id(datos["lista_id"], datos["id"])
    return jsonify(ok=True)


@app.post("/api/tareas/nueva")
@requiere_login
def api_nueva():
    datos = request.json or {}
    titulo = (datos.get("titulo") or "").strip()[:300]
    if not titulo:
        return jsonify(error="Escribe el nombre de la tarea."), 400
    google().crear_tarea(titulo, vence=ahora().date() if datos.get("hoy") else None)
    return jsonify(ok=True)


@app.post("/api/chat")
@requiere_login
def api_chat():
    if not ia_disponible():
        return jsonify(error="Falta configurar la clave de Claude (ANTHROPIC_API_KEY)."), 400
    historial = (request.json or {}).get("historial", [])[-20:]
    historial = [
        {"role": m["role"], "content": str(m["content"])[:2000]}
        for m in historial
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    while historial and historial[0]["role"] != "user":
        historial.pop(0)
    if not historial or historial[-1]["role"] != "user":
        return jsonify(error="Escribe un mensaje."), 400
    momento = ahora()
    dia = momento.date()
    g = google()
    if gemini_disponible():
        agente = Agente(g, cfg, metas, momento)
        imagen, mime = None, "image/jpeg"
        datos_img = (request.json or {}).get("imagen")
        if datos_img:
            import base64
            cabecera, _, b64 = datos_img.partition(",")
            if cabecera.startswith("data:image/"):
                mime = cabecera[5:].split(";")[0]
            imagen = base64.b64decode(b64 or cabecera)
        texto = agente.conversar(historial, imagen, mime)
        return jsonify(respuesta=texto, acciones=agente.acciones)
    eventos, tareas = datos_del_dia(g, dia)
    huecos = huecos_libres(eventos, dia, cfg, desde=momento)
    contexto = construir_contexto(dia, momento, eventos, tareas, huecos, cfg)
    contexto = contexto.replace("\n\nArma mi plan del día.", "")
    if archivo_plan(dia).exists():
        plan = json.loads(archivo_plan(dia).read_text())
        contexto += "\n\nPLAN ACTUAL DE HOY:\n" + "\n".join(
            f"- {b['inicio']}-{b['fin']} {b['titulo']}" for b in plan["bloques"]
        )
    return jsonify(respuesta=conversar(contexto, historial))


@app.get("/api/motivacion")
@requiere_login
def api_motivacion():
    if not gemini_disponible():
        return jsonify(motivacion=None)
    momento = ahora()
    archivo = cfg.carpeta_datos / f"motivacion-{momento.date().isoformat()}.json"
    if archivo.exists() and not request.args.get("nuevo"):
        return jsonify(motivacion=json.loads(archivo.read_text()))
    m = motivacion_del_dia(google(), cfg, metas, momento)
    archivo.write_text(json.dumps(m, ensure_ascii=False))
    return jsonify(motivacion=m)


@app.get("/api/metas")
@requiere_login
def api_metas():
    return jsonify(metas=metas.listar())


@app.post("/api/metas")
@requiere_login
def api_metas_nueva():
    datos = request.json or {}
    texto = (datos.get("texto") or "").strip()
    if not texto:
        return jsonify(error="Escribe tu meta."), 400
    metas.agregar(texto, datos.get("porque", ""))
    return jsonify(metas=metas.listar())


@app.delete("/api/metas/<meta_id>")
@requiere_login
def api_metas_quitar(meta_id):
    metas.quitar(meta_id)
    return jsonify(metas=metas.listar())


if __name__ == "__main__":
    puerto = int(os.getenv("PORT", "8000"))
    print(f"\n🌟 Organizador listo: abre http://localhost:{puerto} en tu navegador\n")
    app.run(host="0.0.0.0", port=puerto, debug=False)
