"""Tu agente de productividad: conversa, te motiva según tus metas y actúa en tu Calendar y Tasks.

Usa Gemini (nivel gratuito de Google) con llamadas a funciones: el modelo decide qué
herramienta usar (crear tarea, mover evento, etc.) y el SDK las ejecuta automáticamente.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, Field

from .config import Config
from .google_api import Google, Tarea, huecos_libres
from .planificador import DIAS, PlanDelDia

MODELOS = [m for m in [os.getenv("GEMINI_MODEL", "").strip(), "gemini-flash-latest", "gemini-3.5-flash", "gemini-2.5-flash"] if m]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


class ErrorIA(RuntimeError):
    pass


def gemini_disponible() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def _cliente() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"].strip())


def _generar(contents, config: types.GenerateContentConfig):
    """Llama a Gemini probando modelos de la lista si alguno no existe."""
    cliente = _cliente()
    ultimo = None
    for modelo in MODELOS:
        try:
            return cliente.models.generate_content(model=modelo, contents=contents, config=config)
        except genai_errors.ClientError as e:
            if e.code == 404:
                ultimo = e
                continue
            if e.code == 429:
                raise ErrorIA("Usaste el límite gratis de la IA por ahora. Intenta en un rato. ⏳") from e
            if e.code in (400, 401, 403) and "API key" in str(e):
                raise ErrorIA("La clave de Gemini (GEMINI_API_KEY) no es válida.") from e
            raise ErrorIA(f"La IA respondió con un error ({e.code}).") from e
        except genai_errors.ServerError as e:
            raise ErrorIA("La IA está saturada, intenta en un momento.") from e
    raise ErrorIA(f"No encontré un modelo de Gemini disponible ({ultimo}).")


# ---------------------------------------------------------------- metas


class Metas:
    """Tus metas personales, guardadas en un archivo JSON."""

    def __init__(self, carpeta: Path):
        self.archivo = carpeta / "metas.json"

    def listar(self) -> list[dict]:
        if not self.archivo.exists():
            return []
        return json.loads(self.archivo.read_text())

    def _guardar(self, metas: list[dict]) -> None:
        self.archivo.write_text(json.dumps(metas, ensure_ascii=False, indent=1))

    def agregar(self, texto: str, porque: str = "") -> dict:
        metas = self.listar()
        meta = {"id": uuid.uuid4().hex[:8], "texto": texto.strip()[:200], "porque": porque.strip()[:300],
                "creada": date.today().isoformat()}
        metas.append(meta)
        self._guardar(metas)
        return meta

    def quitar(self, meta_id: str) -> bool:
        metas = self.listar()
        nuevas = [m for m in metas if m["id"] != meta_id]
        self._guardar(nuevas)
        return len(nuevas) != len(metas)


# ---------------------------------------------------------------- contexto


def _fecha_larga(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} ({d.isoformat()})"


def contexto_general(g: Google, cfg: Config, ahora: datetime, tareas: list[Tarea], metas: list[dict],
                     completadas: list[str]) -> str:
    hoy = ahora.date()
    lineas = [
        f"AHORA: {_fecha_larga(hoy)}, {ahora:%H:%M}. Zona horaria {cfg.zona}.",
        f"Horario productivo del usuario: {cfg.hora_inicio:%H:%M} a {cfg.hora_fin:%H:%M}.",
        "",
        "PRÓXIMOS 7 DÍAS (usa estas fechas exactas):",
    ]
    semana = g.eventos_rango(hoy, 7)
    for d, eventos in semana.items():
        fijos = [e for e in eventos if not e.todo_el_dia]
        texto = "; ".join(
            f"{e.inicio:%H:%M}-{e.fin:%H:%M} {e.titulo}" + (f" [bloque del organizador id={e.id}]" if e.creado_por_organizador else f" [{e.calendario}]")
            for e in fijos
        ) or "sin eventos"
        todo_dia = [f"{e.titulo} [{e.calendario}]" for e in eventos if e.todo_el_dia]
        if todo_dia:
            texto += " | todo el día: " + ", ".join(todo_dia)
        lineas.append(f"- {_fecha_larga(d)}: {texto}")

    lineas += ["", "MÁS ADELANTE (días 8 a 30) — exámenes, PCs, quizzes y pendientes de sus calendarios:"]
    despues = [e for e in g.eventos_entre(hoy + timedelta(days=7), hoy + timedelta(days=30)) if not e.creado_por_organizador]
    lineas += [f"- {_fecha_larga(e.inicio.date())}: {e.titulo} [{e.calendario}]" for e in despues] or ["- (nada)"]

    huecos = huecos_libres(semana[hoy], hoy, cfg, desde=ahora)
    lineas += ["", "HUECOS LIBRES QUE QUEDAN HOY: " + (", ".join(f"{a:%H:%M}-{b:%H:%M}" for a, b in huecos) or "ninguno")]

    lineas += ["", "METAS DEL USUARIO:"]
    lineas += [f"- (id={m['id']}) {m['texto']}" + (f" — por qué: {m['porque']}" if m.get("porque") else "") for m in metas] or [
        "- (todavía no definió metas; anímale a escribir 1 a 3)"]

    lineas += ["", "TAREAS PENDIENTES (número para las herramientas):"]
    for i, t in enumerate(tareas, start=1):
        if t.vence is None:
            estado = "sin fecha"
        elif t.vence < hoy:
            estado = f"VENCIDA {t.vence.isoformat()}"
        elif t.vence == hoy:
            estado = "vence HOY"
        else:
            estado = f"vence {t.vence.isoformat()}"
        lineas.append(f"{i}. {t.titulo} [{estado}]" + (f" — {t.notas[:120]}" if t.notas else ""))
    if not tareas:
        lineas.append("(ninguna)")
    lineas += ["", "COMPLETADAS HOY: " + (", ".join(completadas) if completadas else "ninguna todavía")]
    return "\n".join(lineas)


PERSONALIDAD = """Eres "Orga", el agente personal de productividad y coach motivador del usuario. \
Hablas en español latino (el usuario es de Perú), cercano, con energía positiva pero honesto, \
como un buen amigo que lo empuja a cumplir sus metas. Usa algún emoji, sin exagerar.

Cómo trabajas:
- Conecta siempre lo que el usuario hace hoy con sus METAS: explícale por qué una tarea lo acerca a ellas.
- Sé concreto: propone acciones pequeñas y claras ("empieza con 25 minutos de X a las 16:00").
- Tienes herramientas para actuar de verdad en su Google Tasks y Google Calendar. Úsalas cuando el \
usuario te pida hacer algo o cuando acepte una propuesta tuya. Después de actuar, cuenta brevemente qué hiciste.
- Para crear bloques en el calendario respeta los eventos existentes y su horario productivo; no los superpongas.
- Antes de borrar algo o de hacer muchos cambios a la vez (más de 5), pide confirmación.
- Si te pide planificar la semana: revisa los próximos 7 días, reparte sus tareas y sus metas en bloques \
realistas (máx. 3-4 horas de foco por día, con descansos) y créalos en el calendario.
- Si te pide la revisión del día: celebra lo completado, muestra lo pendiente y propone a qué día moverlo; \
muévelo cuando acepte.
- Respuestas cortas y fáciles de leer en el celular (máximo ~10 líneas), con listas cuando ayuden.
- Usa siempre las fechas exactas que aparecen en el contexto (formato AAAA-MM-DD para las herramientas).
- Sus calendarios incluyen exámenes, PCs, controles y quizzes: trátalos como pendientes importantes. \
Cuando se acerque uno (próximos 7-10 días), propón bloques de estudio antes de la fecha.
- Si el usuario te envía una imagen (sílabo, horario, captura de calendario, tarea, apuntes), léela con \
cuidado, extrae fechas y pendientes, y propón crearlos como tareas o bloques; créalos si te lo pide."""


# ---------------------------------------------------------------- agente


class Agente:
    def __init__(self, g: Google, cfg: Config, metas: Metas, ahora: datetime):
        self.g, self.cfg, self.metas, self.ahora = g, cfg, metas, ahora
        self.tareas: list[Tarea] = []
        self.acciones: list[str] = []

    def _tarea(self, numero: int) -> Tarea:
        if not 1 <= numero <= len(self.tareas):
            raise ValueError(f"No existe la tarea número {numero}.")
        return self.tareas[numero - 1]

    def _dt(self, fecha: str, hora: str) -> datetime:
        d = date.fromisoformat(fecha)
        h = datetime.strptime(hora.strip(), "%H:%M").time()
        return datetime.combine(d, h, self.cfg.zona)

    # ---- herramientas (el modelo las ve por su nombre, docstring y parámetros)

    def herramientas(self):
        agente = self

        def crear_tarea(titulo: str, fecha: str = "") -> str:
            """Crea una tarea nueva en Google Tasks. fecha es opcional, formato AAAA-MM-DD."""
            vence = date.fromisoformat(fecha) if fecha else None
            agente.g.crear_tarea(titulo, vence=vence)
            agente.acciones.append(f"➕ Tarea creada: {titulo}" + (f" ({fecha})" if fecha else ""))
            return "ok"

        def completar_tarea(numero: int) -> str:
            """Marca como completada la tarea con ese número de la lista de pendientes."""
            t = agente._tarea(numero)
            agente.g.completar_tarea_id(t.lista_id, t.id)
            agente.acciones.append(f"✅ Completada: {t.titulo}")
            return "ok"

        def reprogramar_tarea(numero: int, nueva_fecha: str) -> str:
            """Cambia la fecha de vencimiento de una tarea. nueva_fecha en formato AAAA-MM-DD."""
            t = agente._tarea(numero)
            agente.g.cambiar_fecha_tarea(t.lista_id, t.id, date.fromisoformat(nueva_fecha))
            agente.acciones.append(f"📆 Movida: {t.titulo} → {nueva_fecha}")
            return "ok"

        def crear_bloque_calendario(titulo: str, fecha: str, hora_inicio: str, hora_fin: str, nota: str = "") -> str:
            """Crea un bloque de tiempo en Google Calendar. fecha AAAA-MM-DD, horas HH:MM (24 h)."""
            ini, fin = agente._dt(fecha, hora_inicio), agente._dt(fecha, hora_fin)
            if fin <= ini:
                return "error: la hora de fin debe ser después de la de inicio"
            evento_id = agente.g.crear_bloque(f"🎯 {titulo}", ini, fin, nota)
            agente.acciones.append(f"📅 Bloque: {titulo} ({fecha} {hora_inicio}-{hora_fin})")
            return f"ok, id={evento_id}"

        def borrar_bloque_calendario(evento_id: str) -> str:
            """Borra un bloque del calendario creado por el organizador (usa el id que aparece en el contexto)."""
            if agente.g.borrar_evento_organizador(evento_id):
                agente.acciones.append("🗑️ Bloque borrado del calendario")
                return "ok"
            return "error: solo puedo borrar bloques creados por el organizador"

        def agregar_meta(meta: str, porque: str = "") -> str:
            """Guarda una meta personal nueva del usuario (y opcionalmente por qué es importante para él)."""
            agente.metas.agregar(meta, porque)
            agente.acciones.append(f"🏁 Meta agregada: {meta}")
            return "ok"

        def quitar_meta(meta_id: str) -> str:
            """Elimina una meta por su id (cuando el usuario la cumplió o ya no la quiere)."""
            if agente.metas.quitar(meta_id):
                agente.acciones.append("🏁 Meta quitada")
                return "ok"
            return "error: no encontré esa meta"

        return [crear_tarea, completar_tarea, reprogramar_tarea, crear_bloque_calendario,
                borrar_bloque_calendario, agregar_meta, quitar_meta]

    def _contexto(self) -> str:
        hoy = self.ahora.date()
        self.tareas = sorted(self.g.tareas_pendientes(), key=lambda t: (t.vence is None, t.vence or date.max, t.titulo.lower()))
        return contexto_general(self.g, self.cfg, self.ahora, self.tareas, self.metas.listar(),
                                self.g.tareas_completadas_hoy(hoy))

    def conversar(self, historial: list[dict], imagen: bytes | None = None, mime: str = "image/jpeg") -> str:
        contexto = self._contexto()
        contents = [
            types.Content(role="user" if m["role"] == "user" else "model", parts=[types.Part(text=m["content"])])
            for m in historial
        ]
        if imagen:
            contents[-1].parts.insert(0, types.Part.from_bytes(data=imagen, mime_type=mime))
        config = types.GenerateContentConfig(
            system_instruction=PERSONALIDAD + "\n\nCONTEXTO ACTUAL:\n" + contexto,
            tools=self.herramientas(),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=25),
            temperature=0.7,
        )
        respuesta = _generar(contents, config)
        texto = (respuesta.text or "").strip()
        if not texto:
            texto = "Listo. ✅" if self.acciones else "Mmm, no se me ocurrió nada. ¿Me lo dices de otra forma?"
        return texto


# ---------------------------------------------------------------- mensaje motivador del día


class Motivacion(BaseModel):
    titulo: str = Field(description="Frase corta y potente para hoy (máx. 8 palabras), con un emoji")
    mensaje: str = Field(description="2-3 frases motivadoras y personales que conecten el día con sus metas")
    enfoque: list[str] = Field(description="Las 3 acciones concretas que más lo acercan a sus metas hoy")


def motivacion_del_dia(g: Google, cfg: Config, metas: Metas, ahora: datetime) -> dict:
    agente = Agente(g, cfg, metas, ahora)
    contexto = agente._contexto()
    config = types.GenerateContentConfig(
        system_instruction=PERSONALIDAD,
        response_mime_type="application/json",
        response_schema=Motivacion,
        temperature=0.9,
    )
    r = _generar("CONTEXTO:\n" + contexto + "\n\nEscribe mi mensaje motivador de hoy y mis 3 acciones clave.", config)
    if r.parsed is None:
        raise ErrorIA("La IA no devolvió el mensaje, intenta de nuevo.")
    return Motivacion.model_validate(r.parsed).model_dump() if not isinstance(r.parsed, Motivacion) else r.parsed.model_dump()


# ---------------------------------------------------------------- plan del día con Gemini


def plan_con_gemini(contexto: str, metas: list[dict]) -> PlanDelDia:
    from .planificador import SISTEMA

    extra = ""
    if metas:
        extra = "\n\nMETAS DEL USUARIO (incluye al menos un bloque que lo acerque a alguna):\n" + "\n".join(
            f"- {m['texto']}" for m in metas)
    config = types.GenerateContentConfig(
        system_instruction=SISTEMA + "\nEn 'tarea_numero' pon el número de la tarea si el bloque trabaja una tarea; si no, null.",
        response_mime_type="application/json",
        response_schema=PlanDelDia,
        temperature=0.4,
    )
    r = _generar(contexto + extra, config)
    if r.parsed is None:
        raise ErrorIA("La IA no devolvió el plan, intenta de nuevo.")
    return r.parsed if isinstance(r.parsed, PlanDelDia) else PlanDelDia.model_validate(r.parsed)
