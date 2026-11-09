"""Uso:  python -m organizador <comando>

Comandos:
  plan        Claude arma tu plan del día (opciones: --manana, --agendar, --nota "...")
  agenda      Muestra tus eventos de hoy
  tareas      Muestra tus tareas pendientes numeradas
  completar N Marca como completada la tarea número N
  nueva "..." Crea una tarea nueva (opción --hoy para que venza hoy)
  limpiar     Borra los bloques que el Organizador creó hoy en tu calendario
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta

import anthropic

from .config import cargar_config
from .google_api import Google, Tarea, huecos_libres

TIPOS_AGENDABLES = {"tarea", "enfoque", "rutina"}
ICONOS = {"tarea": "✅", "evento": "📅", "descanso": "☕", "enfoque": "🎯", "rutina": "🔁"}


def _ordenar_tareas(tareas: list[Tarea]) -> list[Tarea]:
    # Primero las que tienen fecha (más antiguas primero), luego las sin fecha.
    return sorted(tareas, key=lambda t: (t.vence is None, t.vence or date.max, t.titulo.lower()))


def cmd_agenda(g: Google, cfg, args) -> None:
    hoy = datetime.now(cfg.zona).date()
    eventos = g.eventos_del_dia(hoy)
    print(f"\n📅 Agenda de hoy ({hoy.isoformat()})\n")
    if not eventos:
        print("  No tienes eventos hoy.")
    for e in eventos:
        hora = "Todo el día " if e.todo_el_dia else f"{e.inicio:%H:%M}-{e.fin:%H:%M}"
        marca = " (Organizador)" if e.creado_por_organizador else ""
        print(f"  {hora}  {e.titulo}{marca}")
    print()


def cmd_tareas(g: Google, cfg, args) -> None:
    hoy = datetime.now(cfg.zona).date()
    tareas = _ordenar_tareas(g.tareas_pendientes())
    print(f"\n📝 Tareas pendientes ({len(tareas)})\n")
    for i, t in enumerate(tareas, start=1):
        if t.vence is None:
            fecha = ""
        elif t.vence < hoy:
            fecha = f"  ⚠️ vencida {t.vence:%d/%m}"
        elif t.vence == hoy:
            fecha = "  🔥 hoy"
        else:
            fecha = f"  {t.vence:%d/%m}"
        print(f"  {i:>2}. {t.titulo}{fecha}   [{t.lista}]")
    print()


def cmd_completar(g: Google, cfg, args) -> None:
    tareas = _ordenar_tareas(g.tareas_pendientes())
    if not 1 <= args.numero <= len(tareas):
        sys.exit(f"No existe la tarea {args.numero}. Usa 'tareas' para ver la lista.")
    t = tareas[args.numero - 1]
    g.completar_tarea(t)
    print(f"🎉 ¡Listo! Completaste: {t.titulo}")


def cmd_nueva(g: Google, cfg, args) -> None:
    vence = datetime.now(cfg.zona).date() if args.hoy else None
    g.crear_tarea(args.titulo, vence=vence)
    print(f"➕ Tarea creada: {args.titulo}")


def cmd_limpiar(g: Google, cfg, args) -> None:
    hoy = datetime.now(cfg.zona).date()
    n = g.borrar_bloques_del_organizador(hoy)
    print(f"🧹 Borré {n} bloque(s) del Organizador de hoy.")


def cmd_plan(g: Google, cfg, args) -> None:
    from .planificador import construir_contexto, generar_plan

    ahora = datetime.now(cfg.zona)
    dia = ahora.date() + timedelta(days=1) if args.manana else ahora.date()

    print("⏳ Leyendo tu calendario y tus tareas...")
    eventos = g.eventos_del_dia(dia)
    tareas = _ordenar_tareas(g.tareas_pendientes())
    huecos = huecos_libres(eventos, dia, cfg, desde=ahora if dia == ahora.date() else None)

    contexto = construir_contexto(dia, ahora, eventos, tareas, huecos, cfg, args.nota or "")
    print("🤖 Claude está armando tu plan...\n")
    try:
        plan = generar_plan(contexto)
    except anthropic.AuthenticationError:
        sys.exit("❌ La clave ANTHROPIC_API_KEY no es válida. Revisa tu archivo .env.")
    except anthropic.APIConnectionError:
        sys.exit("❌ No pude conectarme con Claude. Revisa tu conexión a internet.")
    except anthropic.APIStatusError as e:
        sys.exit(f"❌ Error de la API de Claude ({e.status_code}): {e.message}")

    titulo = "mañana" if args.manana else "hoy"
    print("=" * 60)
    print(f"  🌟 TU PLAN PARA {titulo.upper()} ({dia.isoformat()})")
    print("=" * 60)
    print(f"\n{plan.resumen}\n")
    print("🏆 Prioridades:")
    for i, p in enumerate(plan.prioridades, start=1):
        print(f"   {i}. {p}")
    print("\n🗓️  Agenda:")
    for b in plan.bloques:
        icono = ICONOS.get(b.tipo, "•")
        print(f"   {b.inicio}-{b.fin}  {icono} {b.titulo}")
        if b.nota:
            print(f"                 ↳ {b.nota}")
    if plan.tareas_para_otro_dia:
        print("\n📦 Mejor para otro día:")
        for n in plan.tareas_para_otro_dia:
            if 1 <= n <= len(tareas):
                print(f"   - {tareas[n - 1].titulo}")
    print(f"\n💡 {plan.consejo}\n")

    if not args.agendar:
        print("Tip: usa 'plan --agendar' para poner estos bloques en tu Google Calendar.")
        return

    agendables = [b for b in plan.bloques if b.tipo in TIPOS_AGENDABLES]
    if not agendables:
        print("No hay bloques nuevos para agendar.")
        return
    resp = input(f"¿Agrego {len(agendables)} bloque(s) a tu Google Calendar? [s/N] ").strip().lower()
    if resp not in ("s", "si", "sí", "y", "yes"):
        print("Ok, no agendé nada.")
        return

    borrados = g.borrar_bloques_del_organizador(dia)
    if borrados:
        print(f"🧹 Reemplacé {borrados} bloque(s) anteriores del Organizador.")
    creados = 0
    for b in agendables:
        try:
            ini = datetime.combine(dia, datetime.strptime(b.inicio, "%H:%M").time(), cfg.zona)
            fin = datetime.combine(dia, datetime.strptime(b.fin, "%H:%M").time(), cfg.zona)
        except ValueError:
            continue
        if fin <= ini:
            continue
        descripcion = b.nota
        if b.tarea_numero and 1 <= b.tarea_numero <= len(tareas):
            descripcion = f"Tarea: {tareas[b.tarea_numero - 1].titulo}\n{b.nota}"
        g.crear_bloque(f"{ICONOS.get(b.tipo, '')} {b.titulo}".strip(), ini, fin, descripcion)
        creados += 1
    print(f"✅ Agregué {creados} bloque(s) a tu calendario. ¡A darle!")


def main() -> None:
    parser = argparse.ArgumentParser(prog="organizador", description="Tu asistente para organizar el día.")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("plan", help="Claude arma tu plan del día")
    p.add_argument("--manana", action="store_true", help="Planificar el día de mañana")
    p.add_argument("--agendar", action="store_true", help="Crear los bloques en Google Calendar")
    p.add_argument("--nota", help='Indicaciones extra, ej: "hoy quiero salir temprano"')
    p.set_defaults(func=cmd_plan)

    sub.add_parser("agenda", help="Ver eventos de hoy").set_defaults(func=cmd_agenda)
    sub.add_parser("tareas", help="Ver tareas pendientes").set_defaults(func=cmd_tareas)

    p = sub.add_parser("completar", help="Completar una tarea por número")
    p.add_argument("numero", type=int)
    p.set_defaults(func=cmd_completar)

    p = sub.add_parser("nueva", help="Crear una tarea")
    p.add_argument("titulo")
    p.add_argument("--hoy", action="store_true", help="Que venza hoy")
    p.set_defaults(func=cmd_nueva)

    sub.add_parser("limpiar", help="Borrar bloques del Organizador de hoy").set_defaults(func=cmd_limpiar)

    args = parser.parse_args()
    cfg = cargar_config()
    try:
        g = Google(cfg)
    except FileNotFoundError as e:
        sys.exit(f"❌ {e}")
    args.func(g, cfg, args)


if __name__ == "__main__":
    main()
