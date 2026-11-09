"""Claude analiza tu agenda y tus tareas y arma un plan de día productivo."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from .config import Config
from .google_api import Evento, Tarea

MODELO = "claude-opus-5-5"

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


class Bloque(BaseModel):
    inicio: str = Field(description="Hora de inicio en formato HH:MM (24 h)")
    fin: str = Field(description="Hora de fin en formato HH:MM (24 h)")
    titulo: str = Field(description="Título corto del bloque")
    tipo: Literal["tarea", "evento", "descanso", "enfoque", "rutina"]
    tarea_numero: int | None = Field(
        default=None, description="Número de la tarea de la lista si este bloque trabaja una tarea concreta"
    )
    nota: str = Field(default="", description="Consejo breve o primer paso concreto")


class PlanDelDia(BaseModel):
    resumen: str = Field(description="2-3 frases sobre cómo viene el día y la estrategia")
    prioridades: list[str] = Field(description="Las 3 cosas más importantes de hoy, en orden")
    bloques: list[Bloque] = Field(description="Agenda completa del día en orden cronológico")
    tareas_para_otro_dia: list[int] = Field(
        default_factory=list, description="Números de tareas que conviene mover a otro día"
    )
    consejo: str = Field(description="Un consejo de productividad personalizado para hoy")


SISTEMA = """Eres el asistente personal de productividad del usuario. Hablas en español, \
con un tono cercano, motivador y directo.

Tu trabajo es armar un plan realista para el día a partir de su Google Calendar y sus \
Google Tasks:
- Respeta siempre los eventos que ya existen: no los muevas ni los superpongas.
- Coloca las tareas solo dentro de los huecos libres indicados.
- Prioriza lo vencido y lo que vence hoy; después lo importante sin fecha.
- Pon el trabajo que exige más concentración en las primeras horas libres y \
agrupa tareas pequeñas parecidas en un solo bloque.
- Usa bloques de enfoque de 25 a 90 minutos y deja descansos cortos entre bloques \
largos, y un espacio para comer si el horario lo cruza.
- No sobrecargues el día: deja algo de margen libre para imprevistos. Si no cabe todo, \
manda tareas a "tareas_para_otro_dia".
- Incluye los eventos existentes en "bloques" con tipo "evento" para que la agenda \
quede completa."""


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def construir_contexto(
    dia: date,
    ahora: datetime,
    eventos: list[Evento],
    tareas: list[Tarea],
    huecos: list[tuple[datetime, datetime]],
    cfg: Config,
    peticion_extra: str = "",
) -> str:
    lineas = [
        f"Fecha: {DIAS[dia.weekday()]} {dia.isoformat()}",
        f"Hora actual: {_hhmm(ahora)}" if ahora.date() == dia else "Planificando para un día futuro.",
        f"Horario productivo: {cfg.hora_inicio.strftime('%H:%M')} a {cfg.hora_fin.strftime('%H:%M')}",
        "",
        "EVENTOS DEL CALENDARIO:",
    ]
    fijos = [e for e in eventos if not e.creado_por_organizador]
    if not fijos:
        lineas.append("- (ninguno)")
    for e in fijos:
        if e.todo_el_dia:
            lineas.append(f"- Todo el día: {e.titulo}")
        else:
            lineas.append(f"- {_hhmm(e.inicio)}-{_hhmm(e.fin)}: {e.titulo}")

    lineas += ["", "HUECOS LIBRES:"]
    if not huecos:
        lineas.append("- (no hay huecos libres)")
    for a, b in huecos:
        minutos = int((b - a).total_seconds() // 60)
        lineas.append(f"- {_hhmm(a)}-{_hhmm(b)} ({minutos} min)")

    lineas += ["", "TAREAS PENDIENTES:"]
    if not tareas:
        lineas.append("- (ninguna)")
    for i, t in enumerate(tareas, start=1):
        if t.vence is None:
            estado = "sin fecha"
        elif t.vence < dia:
            estado = f"VENCIDA ({t.vence.isoformat()})"
        elif t.vence == dia:
            estado = "VENCE HOY"
        else:
            estado = f"vence {t.vence.isoformat()}"
        nota = f" — {t.notas[:200]}" if t.notas else ""
        lineas.append(f"{i}. [{estado}] {t.titulo} (lista: {t.lista}){nota}")

    if peticion_extra:
        lineas += ["", f"INDICACIONES DEL USUARIO PARA HOY: {peticion_extra}"]

    lineas += ["", "Arma mi plan del día."]
    return "\n".join(lineas)


def generar_plan(contexto: str) -> PlanDelDia:
    client = anthropic.Anthropic()
    respuesta = client.beta.messages.parse(
        model=MODELO,
        max_tokens=16000,
        system=SISTEMA,
        output_config={"effort": "medium"},
        output_format=PlanDelDia,
        # Si el modelo rechaza la petición por error, la API reintenta con otro modelo.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": contexto}],
    )
    if respuesta.stop_reason == "refusal":
        raise RuntimeError("Claude no pudo generar el plan (la petición fue rechazada).")
    if respuesta.stop_reason == "max_tokens" or respuesta.parsed_output is None:
        raise RuntimeError("La respuesta de Claude quedó incompleta. Intenta de nuevo.")
    return respuesta.parsed_output


SISTEMA_CHAT = """Eres el asistente personal de productividad del usuario. Hablas en español, \
con un tono cercano, motivador y directo. Respuestas breves (máximo 6-8 líneas), fáciles \
de leer en el celular; usa listas cortas cuando ayuden.

Conoces su agenda y sus tareas de hoy (abajo). Ayúdale a decidir qué hacer ahora, a \
reorganizar el día si algo cambió, a dividir tareas grandes en pasos pequeños y a no \
procrastinar. Si te pide un plan completo nuevo, sugiérele usar el botón "Generar plan" \
escribiendo sus indicaciones.

SU DÍA:
"""


def conversar(contexto: str, historial: list[dict]) -> str:
    """Responde un mensaje del chat. `historial` es [{role, content}, ...] terminando en user."""
    client = anthropic.Anthropic()
    respuesta = client.beta.messages.create(
        model=MODELO,
        max_tokens=4000,
        system=SISTEMA_CHAT + contexto,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=historial,
    )
    if respuesta.stop_reason == "refusal":
        return "Lo siento, no puedo ayudarte con eso. ¿Probamos con otra pregunta?"
    texto = "".join(b.text for b in respuesta.content if b.type == "text").strip()
    return texto or "No tengo una respuesta ahora mismo, intenta de nuevo."


# ---------------------------------------------------------------- modo gratis (sin IA)

CONSEJOS = [
    "Empieza por la tarea que más te pesa: después todo se siente más liviano.",
    "Deja el celular lejos durante los bloques de enfoque.",
    "Si una tarea te da flojera, comprométete solo a 5 minutos.",
    "Termina una cosa antes de empezar otra.",
    "Toma agua y estírate en cada pausa.",
    "Hecho es mejor que perfecto.",
    "Revisa tu plan a mediodía y ajústalo sin culpa.",
]


def plan_sin_ia(
    dia: date,
    eventos: list[Evento],
    tareas: list[Tarea],
    huecos: list[tuple[datetime, datetime]],
) -> PlanDelDia:
    """Arma un plan con reglas simples: urgente primero, bloques de 45 min con pausas."""
    from datetime import timedelta

    def urgencia(t: Tarea):
        if t.vence is None:
            return (2, date.max)
        if t.vence <= dia:
            return (0, t.vence)
        return (1, t.vence)

    pendientes = sorted(range(len(tareas)), key=lambda i: urgencia(tareas[i]))
    bloques: list[dict] = []
    trabajo = timedelta(minutes=45)
    pausa = timedelta(minutes=10)
    hechos_seguidos = 0

    for a, b in huecos:
        cursor = a
        while pendientes:
            # Almuerzo de 13:00 a 14:00 si el hueco lo cruza
            almuerzo = datetime.combine(dia, datetime.min.time(), a.tzinfo).replace(hour=13)
            if cursor <= almuerzo < b and cursor + trabajo > almuerzo:
                if almuerzo - cursor >= timedelta(minutes=25):
                    i = pendientes.pop(0)
                    bloques.append(dict(inicio=cursor, fin=almuerzo, titulo=tareas[i].titulo, tipo="tarea", tarea_numero=i + 1))
                fin_alm = min(almuerzo + timedelta(hours=1), b)
                bloques.append(dict(inicio=almuerzo, fin=fin_alm, titulo="Almuerzo", tipo="descanso"))
                cursor, hechos_seguidos = fin_alm, 0
                continue
            if b - cursor < timedelta(minutes=25):
                break
            fin = min(cursor + trabajo, b)
            i = pendientes.pop(0)
            t = tareas[i]
            nota = "¡Está vencida, sácala de encima!" if t.vence and t.vence < dia else (
                "Vence hoy." if t.vence == dia else "")
            bloques.append(dict(inicio=cursor, fin=fin, titulo=t.titulo, tipo="tarea", tarea_numero=i + 1, nota=nota))
            cursor = fin
            hechos_seguidos += 1
            if hechos_seguidos >= 2 and b - cursor >= pausa + timedelta(minutes=25):
                bloques.append(dict(inicio=cursor, fin=cursor + pausa, titulo="Pausa", tipo="descanso",
                                    nota="Agua, estirarte, mirar lejos."))
                cursor += pausa
                hechos_seguidos = 0

    for e in eventos:
        if not e.todo_el_dia and not e.creado_por_organizador:
            bloques.append(dict(inicio=e.inicio, fin=e.fin, titulo=e.titulo, tipo="evento"))
    bloques.sort(key=lambda x: x["inicio"])

    urgentes = sum(1 for t in tareas if t.vence and t.vence <= dia)
    n_eventos = sum(1 for e in eventos if not e.creado_por_organizador)
    planeadas = [b for b in bloques if b["tipo"] == "tarea"]
    if not tareas:
        resumen = "No tienes tareas pendientes. ¡Aprovecha para adelantar algo o descansar!"
    else:
        resumen = (
            f"Hoy tienes {n_eventos} evento(s) y {urgentes} tarea(s) urgente(s). "
            f"Acomodé {len(planeadas)} tarea(s) en tus horas libres, empezando por lo más urgente."
        )
    vistas, prioridades = set(), []
    for b in planeadas:
        if b["titulo"] not in vistas:
            vistas.add(b["titulo"])
            prioridades.append(b["titulo"])
        if len(prioridades) == 3:
            break

    return PlanDelDia(
        resumen=resumen,
        prioridades=prioridades or ["Disfrutar tu día"],
        bloques=[
            Bloque(
                inicio=b["inicio"].strftime("%H:%M"),
                fin=b["fin"].strftime("%H:%M"),
                titulo=b["titulo"],
                tipo=b["tipo"],
                tarea_numero=b.get("tarea_numero"),
                nota=b.get("nota", ""),
            )
            for b in bloques
        ],
        tareas_para_otro_dia=[i + 1 for i in pendientes],
        consejo=CONSEJOS[dia.toordinal() % len(CONSEJOS)],
    )
