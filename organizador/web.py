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
from .planificador import DIAS, construir_contexto, conversar, generar_plan, plan_sin_ia

EN_SERVIDOR = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("EN_SERVIDOR"))
if not EN_SERVIDOR:
    # En tu PC la app corre en http://localhost, sin https.
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

cfg = cargar_config()
cfg.carpeta_datos.mkdir(parents=True, exist_ok=True)
ARCHIVO_TOKEN = cfg.carpeta_datos / "google_token.json"

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
)


# ---------------------------------------------------------------- utilidades


def ahora() -> datetime:
    return datetime.now(cfg.zona)


def ia_disponible() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


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
        "ia": ia_disponible(),
        "google": False,
    }
    creds = credenciales_google()
    if creds is None:
        return jsonify(base)
    g = Google(cfg, creds)
    eventos, tareas = datos_del_dia(g, dia)
    completadas = g.tareas_completadas_hoy(dia)
    plan = None
    if archivo_plan(dia).exists():
        plan = json.loads(archivo_plan(dia).read_text())
    base.update(
        google=True,
        eventos=[
            {
                "titulo": e.titulo,
                "inicio": e.inicio.strftime("%H:%M"),
                "fin": e.fin.strftime("%H:%M"),
                "todo_el_dia": e.todo_el_dia,
                "organizador": e.creado_por_organizador,
            }
            for e in eventos
        ],
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
    if ia_disponible():
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


if __name__ == "__main__":
    puerto = int(os.getenv("PORT", "8000"))
    print(f"\n🌟 Organizador listo: abre http://localhost:{puerto} en tu navegador\n")
    app.run(host="0.0.0.0", port=puerto, debug=False)
