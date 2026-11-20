"""Conector de Orga para Claude (servidor MCP por HTTP).

Permite agregar Orga como «conector personalizado» en claude.ai: lo que le pidas a Claude
(ver tu agenda, crear tareas, armar tu horario…) se hace en tu Google Calendar y Google Tasks,
igual que con el agente de Orga. El que piensa es Claude, así que no gasta la cuota de Gemini.

Dirección:  https://<tu-app>/mcp/<clave>
La clave sale de la variable ORGA_MCP_TOKEN (o se genera y guarda en la carpeta de datos).
Implementa el transporte «Streamable HTTP» de MCP respondiendo siempre en JSON (sin SSE).
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import traceback
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, jsonify, request

bp = Blueprint("mcp_orga", __name__)

VERSIONES = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
INSTRUCCIONES = (
    "Orga es el organizador personal del usuario (Perú, zona America/Lima), conectado a su Google Calendar "
    "y Google Tasks. Antes de planificar, mira la agenda y las tareas con las herramientas. Usa fechas "
    "AAAA-MM-DD y horas HH:MM de 24 h en hora de Lima. No superpongas bloques con eventos existentes. "
    "Pide confirmación antes de borrar o de hacer más de 5 cambios a la vez. Responde en español."
)
TIPOS_BLOQUE = ["tarea", "evento", "descanso", "enfoque", "rutina"]


def _w():
    """La app principal (importación diferida para evitar ciclos)."""
    from . import web
    return web


def clave() -> str:
    if os.getenv("ORGA_MCP_TOKEN", "").strip():
        return os.environ["ORGA_MCP_TOKEN"].strip()
    w = _w()
    archivo = w.cfg.carpeta_datos / "mcp_token"
    if not archivo.exists():
        archivo.write_text(secrets.token_urlsafe(24))
    return archivo.read_text().strip()


# ---------------------------------------------------------------- utilidades de las herramientas


class ErrorUsuario(Exception):
    """Error que se le explica a Claude tal cual."""


def _fecha(texto: str, campo: str = "fecha") -> date:
    try:
        return date.fromisoformat(str(texto).strip())
    except ValueError as e:
        raise ErrorUsuario(f"«{campo}» debe tener el formato AAAA-MM-DD (recibí {texto!r}).") from e


def _hora(texto: str, campo: str):
    try:
        return datetime.strptime(str(texto).strip(), "%H:%M").time()
    except ValueError as e:
        raise ErrorUsuario(f"«{campo}» debe tener el formato HH:MM de 24 h (recibí {texto!r}).") from e


def _id_tarea(t) -> str:
    return f"{t.lista_id}:{t.id}"


def _buscar_tarea(g, id_tarea: str):
    lista_id, _, tarea_id = str(id_tarea).partition(":")
    for t in g.tareas_pendientes():
        if t.id == tarea_id and (not lista_id or t.lista_id == lista_id):
            return t
    raise ErrorUsuario(f"No encontré una tarea pendiente con id {id_tarea!r}. Usa ver_tareas para ver los ids.")


def _lista(g, ref: str) -> dict:
    """Un proyecto (lista de Google Tasks) por su id o por su nombre."""
    ref = str(ref or "").strip()
    listas = g.listas()
    for l in listas:
        if l["id"] == ref:
            return l
    coinciden = [l for l in listas if l["nombre"].strip().lower() == ref.lower()]
    if len(coinciden) == 1:
        return coinciden[0]
    raise ErrorUsuario(f"No encontré el proyecto {ref!r}. Proyectos: " + ", ".join(f"«{l['nombre']}» (id={l['id']})" for l in listas))


def _texto_tarea(t, hoy: date) -> str:
    if t.vence is None:
        estado = "sin fecha"
    elif t.vence < hoy:
        estado = f"VENCIDA ({t.vence.isoformat()})"
    elif t.vence == hoy:
        estado = "vence HOY"
    else:
        estado = f"vence {t.vence.isoformat()}"
    return f"- {t.titulo} [{estado}] (proyecto «{t.lista}», id={_id_tarea(t)})" + (f" — {t.notas[:150]}" if t.notas else "")


# ---------------------------------------------------------------- herramientas


def ver_resumen(_: dict) -> str:
    w = _w()
    from .agente import contexto_general
    g, ahora = w.google(), w.ahora()
    tareas = w.ordenar(g.tareas_pendientes())
    texto = contexto_general(g, w.cfg, ahora, tareas, w.metas.listar(), g.tareas_completadas_hoy(ahora.date()))
    ids = "\n".join(f"{i}. id={_id_tarea(t)}" for i, t in enumerate(tareas, start=1))
    return texto + ("\n\nIDS DE LAS TAREAS (úsalos en completar_tarea / reprogramar_tarea):\n" + ids if ids else "")


def ver_agenda(a: dict) -> str:
    w = _w()
    hoy = w.ahora().date()
    desde = _fecha(a["fecha"]) if a.get("fecha") else hoy
    dias = max(1, min(14, int(a.get("dias") or 1)))
    g = w.google()
    pendientes = g.tareas_pendientes()
    salida = []
    for d, eventos in g.eventos_rango(desde, dias).items():
        cumplidos = w.agenda_cumplida(d)
        salida.append(f"## {d.isoformat()} ({w.DIAS[d.weekday()]})")
        for e in eventos:
            if e.todo_el_dia:
                cuando = "todo el día"
            else:
                cuando = f"{e.inicio:%H:%M}-{e.fin:%H:%M}"
            origen = "bloque de Orga" if e.creado_por_organizador else f"calendario «{e.calendario}»"
            salida.append(f"- {cuando} {e.titulo} ({origen}, id={e.id})" + (" ✔ cumplido" if e.id in cumplidos else ""))
        if not eventos:
            salida.append("- (sin eventos)")
        vencen = [t for t in pendientes if t.vence == d]
        if vencen:
            salida.append("Tareas que vencen este día:")
            salida += [_texto_tarea(t, hoy) for t in vencen]
        plan = w.archivo_plan(d)
        if plan.exists():
            p = json.loads(plan.read_text())
            salida.append(f"(Hay un horario de Orga guardado para este día; {'ya está' if p.get('agendado') else 'no está'} en el calendario.)")
    return "\n".join(salida)


def ver_tareas(a: dict) -> str:
    w = _w()
    hoy = w.ahora().date()
    g = w.google()
    tareas = w.ordenar(g.tareas_pendientes())
    if a.get("proyecto"):
        l = _lista(g, a["proyecto"])
        tareas = [t for t in tareas if t.lista_id == l["id"]]
    texto = "TAREAS PENDIENTES:\n" + ("\n".join(_texto_tarea(t, hoy) for t in tareas) or "(ninguna)")
    if a.get("incluir_completadas"):
        hechas = g.tareas_completadas(14)
        texto += "\n\nCOMPLETADAS EN LOS ÚLTIMOS 14 DÍAS (se pueden reabrir):\n" + (
            "\n".join(f"- {t.titulo} (proyecto «{t.lista}», id={_id_tarea(t)})" for t in hechas) or "(ninguna)")
    else:
        texto += "\n\nCOMPLETADAS HOY: " + (", ".join(g.tareas_completadas_hoy(hoy)) or "ninguna")
    return texto


def ver_proyectos(_: dict) -> str:
    w = _w()
    g = w.google()
    pendientes = g.tareas_pendientes()
    return "PROYECTOS (listas de Google Tasks):\n" + "\n".join(
        f"- {l['nombre']} (id={l['id']}): {sum(1 for t in pendientes if t.lista_id == l['id'])} tareas pendientes" for l in g.listas())


def crear_proyecto(a: dict) -> str:
    nombre = str(a.get("nombre", "")).strip()[:100]
    if not nombre:
        raise ErrorUsuario("Falta el nombre del proyecto.")
    l = _w().google().crear_lista(nombre)
    return f"Proyecto creado: «{l['nombre']}» (id={l['id']})."


def renombrar_proyecto(a: dict) -> str:
    nombre = str(a.get("nombre_nuevo", "")).strip()[:100]
    if not nombre:
        raise ErrorUsuario("Falta el nombre nuevo.")
    g = _w().google()
    l = _lista(g, a.get("proyecto", ""))
    g.renombrar_lista(l["id"], nombre)
    return f"Proyecto renombrado: «{l['nombre']}» → «{nombre}»."


def borrar_proyecto(a: dict) -> str:
    g = _w().google()
    l = _lista(g, a.get("proyecto", ""))
    n = sum(1 for t in g.tareas_pendientes() if t.lista_id == l["id"])
    if not a.get("confirmado"):
        raise ErrorUsuario(f"Borrar «{l['nombre']}» elimina también sus {n} tareas pendientes. Pide confirmación al usuario y repite con confirmado=true.")
    if len(g.listas()) <= 1:
        raise ErrorUsuario("Es tu único proyecto: Google Tasks no permite borrarlo. Puedes renombrarlo.")
    g.borrar_lista(l["id"])
    return f"Proyecto «{l['nombre']}» borrado (con {n} tareas pendientes)."


def editar_tarea(a: dict) -> str:
    w = _w()
    g = w.google()
    t = _buscar_tarea(g, a.get("id", ""))
    cambios = []
    titulo = str(a["titulo"]).strip()[:200] if a.get("titulo") is not None else None
    if titulo is not None and not titulo:
        raise ErrorUsuario("El título no puede quedar vacío.")
    notas = str(a["notas"])[:1000] if a.get("notas") is not None else None
    if titulo is not None or notas is not None:
        g.editar_tarea(t.lista_id, t.id, titulo=titulo, notas=notas)
        cambios += ([f"título «{t.titulo}» → «{titulo}»"] if titulo is not None else []) + (["notas actualizadas"] if notas is not None else [])
    if "fecha" in a:
        nueva = _fecha(a["fecha"]) if a.get("fecha") else None
        g.cambiar_fecha_tarea(t.lista_id, t.id, nueva)
        cambios.append(f"fecha → {nueva.isoformat()}" if nueva else "sin fecha")
    if a.get("proyecto"):
        destino = _lista(g, a["proyecto"])
        if destino["id"] != t.lista_id:
            g.mover_tarea(t.lista_id, t.id, destino["id"])
            cambios.append(f"movida al proyecto «{destino['nombre']}» (su id cambió; usa ver_tareas)")
    if not cambios:
        raise ErrorUsuario("No indicaste qué cambiar (titulo, notas, fecha o proyecto).")
    return f"Tarea «{titulo or t.titulo}» actualizada: " + "; ".join(cambios) + "."


def borrar_tarea(a: dict) -> str:
    g = _w().google()
    t = _buscar_tarea(g, a.get("id", ""))
    g.borrar_tarea(t.lista_id, t.id)
    return f"Tarea borrada: «{t.titulo}»."


def reabrir_tarea(a: dict) -> str:
    g = _w().google()
    lista_id, _, tarea_id = str(a.get("id", "")).partition(":")
    t = next((x for x in g.tareas_completadas(30) if x.id == tarea_id and x.lista_id == lista_id), None)
    if t is None:
        raise ErrorUsuario("No encontré esa tarea completada. Usa ver_tareas con incluir_completadas=true.")
    g.reabrir_tarea(t.lista_id, t.id)
    return f"Tarea reabierta: «{t.titulo}» vuelve a estar pendiente."


def crear_tarea(a: dict) -> str:
    w = _w()
    titulo = str(a.get("titulo", "")).strip()[:200]
    if not titulo:
        raise ErrorUsuario("Falta el título de la tarea.")
    vence = _fecha(a["fecha"]) if a.get("fecha") else None
    g = w.google()
    lista = _lista(g, a["proyecto"]) if a.get("proyecto") else None
    g.crear_tarea(titulo, vence=vence, notas=str(a.get("notas", ""))[:1000], lista_id=lista["id"] if lista else None)
    return (f"Tarea creada: «{titulo}»" + (f" para el {vence.isoformat()}" if vence else " (sin fecha)")
            + (f" en el proyecto «{lista['nombre']}»" if lista else "") + ".")


def completar_tarea(a: dict) -> str:
    w = _w()
    g = w.google()
    t = _buscar_tarea(g, a.get("id", ""))
    g.completar_tarea_id(t.lista_id, t.id)
    return f"Tarea completada: «{t.titulo}»."


def reprogramar_tarea(a: dict) -> str:
    w = _w()
    g = w.google()
    t = _buscar_tarea(g, a.get("id", ""))
    nueva = _fecha(a["fecha"]) if a.get("fecha") else None
    g.cambiar_fecha_tarea(t.lista_id, t.id, nueva)
    return f"«{t.titulo}» ahora " + (f"vence el {nueva.isoformat()}." if nueva else "no tiene fecha.")


def crear_evento(a: dict) -> str:
    w = _w()
    d = _fecha(a.get("fecha", ""))
    ini = datetime.combine(d, _hora(a.get("hora_inicio", ""), "hora_inicio"), w.cfg.zona)
    fin = datetime.combine(d, _hora(a.get("hora_fin", ""), "hora_fin"), w.cfg.zona)
    if fin <= ini:
        raise ErrorUsuario("La hora de fin debe ser después de la de inicio.")
    titulo = str(a.get("titulo", "")).strip()[:150]
    if not titulo:
        raise ErrorUsuario("Falta el título del evento.")
    evento_id = w.google().crear_bloque(titulo, ini, fin, str(a.get("nota", ""))[:1000])
    return f"Evento creado: «{titulo}» el {d.isoformat()} de {ini:%H:%M} a {fin:%H:%M} (id={evento_id})."


def borrar_evento(a: dict) -> str:
    g = _w().google()
    evento_id = str(a.get("id", ""))
    if not g.es_bloque_organizador(evento_id) and not a.get("confirmado"):
        raise ErrorUsuario("Ese evento no lo creó Orga (es de uno de tus calendarios). Pide confirmación al usuario y repite con confirmado=true.")
    try:
        titulo = g.borrar_evento(evento_id)
    except LookupError:
        raise ErrorUsuario("No encontré ese evento. Usa ver_agenda para ver los ids.") from None
    return f"Evento borrado: «{titulo}»."


def editar_evento(a: dict) -> str:
    w = _w()
    g = w.google()
    evento_id = str(a.get("id", ""))
    try:
        _, actual = g._ubicar_evento(evento_id)
    except LookupError:
        raise ErrorUsuario("No encontré ese evento. Usa ver_agenda para ver los ids.") from None
    if "dateTime" in actual["start"]:
        dia_actual = datetime.fromisoformat(actual["start"]["dateTime"]).astimezone(w.cfg.zona).date()
    else:
        dia_actual = date.fromisoformat(actual["start"]["date"])
    d = _fecha(a["fecha"]) if a.get("fecha") else dia_actual
    ini = datetime.combine(d, _hora(a["hora_inicio"], "hora_inicio"), w.cfg.zona) if a.get("hora_inicio") else None
    fin = datetime.combine(d, _hora(a["hora_fin"], "hora_fin"), w.cfg.zona) if a.get("hora_fin") else None
    if a.get("fecha") and ini is None:
        if "dateTime" not in actual["start"]:
            raise ErrorUsuario("Es un evento de todo el día: indica también hora_inicio y hora_fin para moverlo.")
        ini = datetime.combine(d, datetime.fromisoformat(actual["start"]["dateTime"]).astimezone(w.cfg.zona).time(), w.cfg.zona)
    titulo = str(a["titulo"]).strip()[:150] if a.get("titulo") else None
    nota = str(a["nota"])[:1000] if a.get("nota") is not None else None
    if titulo is None and nota is None and ini is None and fin is None:
        raise ErrorUsuario("No indicaste qué cambiar (titulo, fecha, hora_inicio, hora_fin o nota).")
    try:
        e = g.editar_evento(evento_id, titulo=titulo, inicio=ini, fin=fin, descripcion=nota)
    except ValueError as err:
        raise ErrorUsuario(str(err)) from None
    s, f = e["start"], e["end"]
    cuando = (f"{datetime.fromisoformat(s['dateTime']).astimezone(w.cfg.zona):%Y-%m-%d %H:%M}-{datetime.fromisoformat(f['dateTime']).astimezone(w.cfg.zona):%H:%M}"
              if "dateTime" in s else f"{s['date']} (todo el día)")
    return f"Evento actualizado: «{e.get('summary', '')}» {cuando}."


def ver_huecos_libres(a: dict) -> str:
    import dataclasses

    from .google_api import huecos_libres
    w = _w()
    ahora = w.ahora()
    d = _fecha(a["fecha"]) if a.get("fecha") else ahora.date()
    ventana = dataclasses.replace(
        w.cfg,
        hora_inicio=_hora(a["desde"], "desde") if a.get("desde") else w.cfg.hora_inicio,
        hora_fin=_hora(a["hasta"], "hasta") if a.get("hasta") else w.cfg.hora_fin,
    )
    huecos = huecos_libres(w.google().eventos_del_dia(d), d, ventana, desde=ahora if d == ahora.date() else None)
    if not huecos:
        return f"No hay tiempo libre el {d.isoformat()} entre {ventana.hora_inicio:%H:%M} y {ventana.hora_fin:%H:%M}."
    total = int(sum((b - x).total_seconds() for x, b in huecos) // 60)
    return f"Huecos libres el {d.isoformat()} ({total} min en total): " + ", ".join(f"{x:%H:%M}-{b:%H:%M}" for x, b in huecos)


def guardar_horario(a: dict) -> str:
    """Guarda un horario hecho por Claude para que aparezca en la sección «Tu horario» de Orga."""
    w = _w()
    hoy = w.ahora().date()
    d = _fecha(a["fecha"]) if a.get("fecha") else hoy
    if d not in (hoy, hoy + timedelta(days=1)):
        raise ErrorUsuario("Orga muestra horarios solo de hoy y de mañana. Para otros días usa crear_evento.")
    bloques = []
    for b in a.get("bloques") or []:
        ini, fin = _hora(b.get("inicio", ""), "inicio"), _hora(b.get("fin", ""), "fin")
        if fin <= ini:
            raise ErrorUsuario(f"El bloque «{b.get('titulo', '')}» termina antes de empezar.")
        tipo = b.get("tipo") if b.get("tipo") in TIPOS_BLOQUE else "tarea"
        bloques.append({"inicio": ini.strftime("%H:%M"), "fin": fin.strftime("%H:%M"), "titulo": str(b.get("titulo", "")).strip()[:120] or "Bloque",
                        "tipo": tipo, "tarea_numero": None, "nota": str(b.get("nota", ""))[:300]})
    if not bloques:
        raise ErrorUsuario("El horario necesita al menos un bloque.")
    bloques.sort(key=lambda b: b["inicio"])
    plan = {
        "resumen": str(a.get("resumen", "")).strip()[:600] or "Horario armado con Claude.",
        "prioridades": [str(p)[:150] for p in (a.get("prioridades") or [])][:5],
        "bloques": bloques,
        "consejo": str(a.get("consejo", "")).strip()[:400],
        "otro_dia": [str(p)[:150] for p in (a.get("para_otro_dia") or [])][:15],
        "generado": w.ahora().strftime("%H:%M"),
        "agendado": False,
        "dia": d.isoformat(),
        "ventana": {"desde": bloques[0]["inicio"], "hasta": bloques[-1]["fin"],
                    "libre": sum((datetime.strptime(b["fin"], "%H:%M") - datetime.strptime(b["inicio"], "%H:%M")).seconds // 60 for b in bloques)},
        "origen": "claude",
    }
    w.archivo_plan(d).write_text(json.dumps(plan, ensure_ascii=False))
    texto = f"Horario guardado en Orga para el {d.isoformat()} ({len(bloques)} bloques)."
    if a.get("poner_en_calendario"):
        g = w.google()
        g.borrar_bloques_del_organizador(d)
        creados = 0
        for b in bloques:
            if b["tipo"] not in w.TIPOS_AGENDABLES:
                continue
            ini = datetime.combine(d, datetime.strptime(b["inicio"], "%H:%M").time(), w.cfg.zona)
            fin = datetime.combine(d, datetime.strptime(b["fin"], "%H:%M").time(), w.cfg.zona)
            g.crear_bloque(f"{w.ICONOS.get(b['tipo'], '')} {b['titulo']}".strip(), ini, fin, b["nota"])
            creados += 1
        plan["agendado"] = True
        w.archivo_plan(d).write_text(json.dumps(plan, ensure_ascii=False))
        texto += f" También creé {creados} bloques en Google Calendar (reemplazando los bloques anteriores de Orga de ese día)."
    return texto


def marcar_cumplido(a: dict) -> str:
    w = _w()
    hoy = w.ahora().date()
    evento_id = str(a.get("id", "")).strip()[:300]
    if not evento_id:
        raise ErrorUsuario("Falta el id del evento (sale en ver_agenda).")
    cumplidos = w.agenda_cumplida(hoy)
    if a.get("hecho", True):
        cumplidos.add(evento_id)
    else:
        cumplidos.discard(evento_id)
    w.archivo_agenda(hoy).write_text(json.dumps(sorted(cumplidos)))
    return "Marcado como cumplido en la agenda de hoy." if a.get("hecho", True) else "Desmarcado."


def ver_metas(_: dict) -> str:
    metas = _w().metas.listar()
    return "METAS:\n" + ("\n".join(f"- {m['texto']} (id={m['id']})" + (f" — por qué: {m['porque']}" if m.get("porque") else "") for m in metas)
                         or "(todavía no hay metas)")


def agregar_meta(a: dict) -> str:
    texto = str(a.get("meta", "")).strip()
    if not texto:
        raise ErrorUsuario("Falta el texto de la meta.")
    m = _w().metas.agregar(texto, str(a.get("porque", "")))
    return f"Meta guardada: «{m['texto']}» (id={m['id']})."


def quitar_meta(a: dict) -> str:
    if _w().metas.quitar(str(a.get("id", ""))):
        return "Meta quitada."
    raise ErrorUsuario("No encontré esa meta. Usa ver_metas para ver los ids.")


def _p(tipo: str, desc: str) -> dict:
    return {"type": tipo, "description": desc}


SOLO_LECTURA = {"readOnlyHint": True, "openWorldHint": True}
ESCRITURA = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}
HERRAMIENTAS = {
    "ver_resumen": (ver_resumen, "Panorama completo: agenda de los próximos 7 días, exámenes de los próximos 30, huecos libres de hoy, metas, tareas pendientes y lo completado hoy. Úsalo primero para planificar o aconsejar.",
                    {}, [], SOLO_LECTURA),
    "ver_agenda": (ver_agenda, "Eventos de Google Calendar (con sus ids) y tareas que vencen, para uno o varios días.",
                   {"fecha": _p("string", "Primer día, AAAA-MM-DD (por defecto hoy)"), "dias": _p("integer", "Cuántos días mostrar, 1 a 14 (por defecto 1)")}, [], SOLO_LECTURA),
    "ver_tareas": (ver_tareas, "Tareas pendientes de Google Tasks con su id, fecha y proyecto, y lo completado hoy.",
                   {"proyecto": _p("string", "Nombre o id de un proyecto para ver solo sus tareas (opcional)"),
                    "incluir_completadas": _p("boolean", "true para listar también las completadas de los últimos 14 días (para reabrirlas)")}, [], SOLO_LECTURA),
    "ver_proyectos": (ver_proyectos, "Proyectos del usuario (las listas de Google Tasks) con su id y cuántas tareas pendientes tienen.", {}, [], SOLO_LECTURA),
    "ver_huecos_libres": (ver_huecos_libres, "Tiempo libre de un día entre dos horas, descontando los eventos del calendario.",
                          {"fecha": _p("string", "AAAA-MM-DD (por defecto hoy)"), "desde": _p("string", "HH:MM (por defecto el inicio de su horario productivo)"),
                           "hasta": _p("string", "HH:MM (por defecto el fin de su horario productivo)")}, [], SOLO_LECTURA),
    "ver_metas": (ver_metas, "Metas personales del usuario guardadas en Orga.", {}, [], SOLO_LECTURA),
    "crear_tarea": (crear_tarea, "Crea una tarea en Google Tasks.",
                    {"titulo": _p("string", "Título de la tarea"), "fecha": _p("string", "Vencimiento AAAA-MM-DD (opcional)"), "notas": _p("string", "Notas (opcional)"),
                     "proyecto": _p("string", "Nombre o id del proyecto donde crearla (opcional; por defecto el primero)")},
                    ["titulo"], ESCRITURA),
    "editar_tarea": (editar_tarea, "Edita una tarea: cambia su título (nombre), notas, fecha o la mueve a otro proyecto. Solo envía lo que cambia.",
                     {"id": _p("string", "id de la tarea (de ver_tareas)"), "titulo": _p("string", "Nuevo título"), "notas": _p("string", "Nuevas notas (reemplazan las anteriores)"),
                      "fecha": _p("string", "Nueva fecha AAAA-MM-DD; vacío para quitar la fecha"), "proyecto": _p("string", "Nombre o id del proyecto al que moverla")},
                     ["id"], ESCRITURA),
    "borrar_tarea": (borrar_tarea, "Borra una tarea (no la marca como hecha: la elimina). Confirma con el usuario antes.",
                     {"id": _p("string", "id de la tarea (de ver_tareas)")}, ["id"], {**ESCRITURA, "destructiveHint": True}),
    "reabrir_tarea": (reabrir_tarea, "Vuelve a poner como pendiente una tarea completada.",
                      {"id": _p("string", "id de la tarea completada (de ver_tareas con incluir_completadas=true)")}, ["id"], ESCRITURA),
    "crear_proyecto": (crear_proyecto, "Crea un proyecto nuevo (una lista en Google Tasks).", {"nombre": _p("string", "Nombre del proyecto")}, ["nombre"], ESCRITURA),
    "renombrar_proyecto": (renombrar_proyecto, "Cambia el nombre de un proyecto.",
                           {"proyecto": _p("string", "Nombre actual o id"), "nombre_nuevo": _p("string", "Nombre nuevo")}, ["proyecto", "nombre_nuevo"], ESCRITURA),
    "borrar_proyecto": (borrar_proyecto, "Borra un proyecto y todas sus tareas. Requiere confirmado=true después de preguntar al usuario.",
                        {"proyecto": _p("string", "Nombre o id"), "confirmado": _p("boolean", "true solo si el usuario ya confirmó")}, ["proyecto"],
                        {**ESCRITURA, "destructiveHint": True}),
    "completar_tarea": (completar_tarea, "Marca una tarea como completada.", {"id": _p("string", "id de la tarea (de ver_tareas)")}, ["id"], ESCRITURA),
    "reprogramar_tarea": (reprogramar_tarea, "Cambia la fecha de una tarea (fecha vacía la deja sin fecha).",
                          {"id": _p("string", "id de la tarea (de ver_tareas)"), "fecha": _p("string", "Nueva fecha AAAA-MM-DD")}, ["id"], ESCRITURA),
    "crear_evento": (crear_evento, "Crea un evento o bloque de tiempo en Google Calendar (queda marcado como de Orga).",
                     {"titulo": _p("string", "Título"), "fecha": _p("string", "AAAA-MM-DD"), "hora_inicio": _p("string", "HH:MM"), "hora_fin": _p("string", "HH:MM"),
                      "nota": _p("string", "Descripción (opcional)")}, ["titulo", "fecha", "hora_inicio", "hora_fin"], ESCRITURA),
    "editar_evento": (editar_evento, "Edita un evento de cualquiera de sus calendarios: título, fecha, horario o descripción. Solo envía lo que cambia; si cambias la fecha sin horas, conserva el horario.",
                      {"id": _p("string", "id del evento (de ver_agenda)"), "titulo": _p("string", "Nuevo título"), "fecha": _p("string", "Nueva fecha AAAA-MM-DD"),
                       "hora_inicio": _p("string", "HH:MM"), "hora_fin": _p("string", "HH:MM (si solo cambias el inicio, se conserva la duración)"),
                       "nota": _p("string", "Nueva descripción")}, ["id"], ESCRITURA),
    "borrar_evento": (borrar_evento, "Borra un evento. Los de Orga se borran directo; los de otros calendarios requieren confirmado=true después de preguntar al usuario.",
                      {"id": _p("string", "id del evento (de ver_agenda)"), "confirmado": _p("boolean", "true solo si el usuario ya confirmó")}, ["id"],
                      {**ESCRITURA, "destructiveHint": True}),
    "guardar_horario": (guardar_horario, "Guarda el horario del día que armaste para que aparezca en la sección «Tu horario» de Orga (solo hoy o mañana). Opcionalmente lo pone en Google Calendar.",
                        {"fecha": _p("string", "AAAA-MM-DD, hoy o mañana (por defecto hoy)"), "resumen": _p("string", "2-3 frases sobre el día"),
                         "prioridades": {"type": "array", "items": {"type": "string"}, "description": "Las 3 cosas más importantes"},
                         "bloques": {"type": "array", "description": "Bloques en orden; incluye los eventos existentes con tipo «evento»",
                                     "items": {"type": "object", "properties": {"inicio": _p("string", "HH:MM"), "fin": _p("string", "HH:MM"), "titulo": _p("string", "Título"),
                                                                                "tipo": {"type": "string", "enum": TIPOS_BLOQUE}, "nota": _p("string", "Primer paso o consejo")},
                                               "required": ["inicio", "fin", "titulo", "tipo"]}},
                         "consejo": _p("string", "Un consejo para el día"),
                         "para_otro_dia": {"type": "array", "items": {"type": "string"}, "description": "Tareas que no entraron"},
                         "poner_en_calendario": _p("boolean", "true para crear también los bloques en Google Calendar")},
                        ["bloques"], ESCRITURA),
    "marcar_cumplido": (marcar_cumplido, "Marca (o desmarca) un evento de hoy como cumplido en la agenda de Orga.",
                        {"id": _p("string", "id del evento (de ver_agenda)"), "hecho": _p("boolean", "false para desmarcar")}, ["id"], ESCRITURA),
    "agregar_meta": (agregar_meta, "Guarda una meta personal nueva.", {"meta": _p("string", "La meta"), "porque": _p("string", "Por qué le importa (opcional)")},
                     ["meta"], ESCRITURA),
    "quitar_meta": (quitar_meta, "Quita una meta (cumplida o descartada).", {"id": _p("string", "id de la meta (de ver_metas)")}, ["id"], {**ESCRITURA, "destructiveHint": True}),
}


def _lista_herramientas() -> list[dict]:
    return [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": props, "required": req},
             "annotations": {**anot, "title": n.replace("_", " ").capitalize()}}
            for n, (_, d, props, req, anot) in HERRAMIENTAS.items()]


def _llamar(nombre: str, argumentos: dict) -> dict:
    from googleapiclient.errors import HttpError
    if nombre not in HERRAMIENTAS:
        raise KeyError(nombre)
    try:
        texto, error = HERRAMIENTAS[nombre][0](argumentos or {}), False
    except ErrorUsuario as e:
        texto, error = str(e), True
    except PermissionError:
        texto, error = ("Orga perdió la conexión con Google. Pide al usuario que abra Orga y pulse «Conectar Google» "
                        "(pasa cada 7 días mientras la app de Google esté en modo de prueba)."), True
    except HttpError as e:
        texto = (f"Google no dejó hacer el cambio ({e.status_code}): ese calendario o lista es de solo lectura para el usuario."
                 if e.status_code == 403 else f"Google respondió con un error ({e.status_code}).")
        error = True
    except Exception as e:  # noqa: BLE001 — se informa a Claude en lugar de romper la conexión
        traceback.print_exc()
        texto, error = f"Error inesperado en Orga: {type(e).__name__}.", True
    return {"content": [{"type": "text", "text": texto}], "isError": error}


# ---------------------------------------------------------------- protocolo (JSON-RPC 2.0)


def _respuesta(mid, resultado=None, error=None) -> dict:
    r = {"jsonrpc": "2.0", "id": mid}
    if error:
        r["error"] = error
    else:
        r["result"] = resultado
    return r


def _atender(m: dict) -> dict | None:
    if not isinstance(m, dict) or m.get("jsonrpc") != "2.0" or "method" not in m:
        return _respuesta(m.get("id") if isinstance(m, dict) else None, error={"code": -32600, "message": "Solicitud no válida"})
    metodo, mid, params = m["method"], m.get("id"), m.get("params") or {}
    if "id" not in m:                    # notificación (p. ej. notifications/initialized): no se responde
        return None
    if metodo == "initialize":
        pedida = params.get("protocolVersion")
        return _respuesta(mid, {
            "protocolVersion": pedida if pedida in VERSIONES else VERSIONES[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "orga", "title": "Orga — tu organizador", "version": "1.1.0"},
            "instructions": INSTRUCCIONES,
        })
    if metodo == "ping":
        return _respuesta(mid, {})
    if metodo == "tools/list":
        return _respuesta(mid, {"tools": _lista_herramientas()})
    if metodo == "tools/call":
        try:
            return _respuesta(mid, _llamar(params.get("name", ""), params.get("arguments") or {}))
        except KeyError:
            return _respuesta(mid, error={"code": -32602, "message": f"Herramienta desconocida: {params.get('name')}"})
    if metodo in ("resources/list", "prompts/list"):
        return _respuesta(mid, {metodo.split("/")[0]: []})
    return _respuesta(mid, error={"code": -32601, "message": f"Método no soportado: {metodo}"})


@bp.route("/mcp/<token>", methods=["GET", "POST", "DELETE"])
def mcp(token):
    if not hmac.compare_digest(token.encode(), clave().encode()):
        return jsonify(error="No autorizado"), 404
    if request.method != "POST":
        return Response(status=405, headers={"Allow": "POST"})
    cuerpo = request.get_json(silent=True)
    if cuerpo is None:
        return jsonify(_respuesta(None, error={"code": -32700, "message": "JSON no válido"})), 400
    if isinstance(cuerpo, list):
        respuestas = [r for r in (_atender(m) for m in cuerpo) if r is not None]
        return (jsonify(respuestas), 200) if respuestas else Response(status=202)
    r = _atender(cuerpo)
    return (jsonify(r), 200) if r is not None else Response(status=202)
