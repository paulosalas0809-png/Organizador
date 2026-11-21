"""Plan de estudio: materias con prioridad (alta, media, baja) y bloques de estudio por día.

Se guarda en CARPETA_DATOS/estudio.json. Lo llenan Claude (conector MCP) y la sección «Estudio» de Orga.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import date, datetime
from pathlib import Path

PRIORIDADES = ["alta", "media", "baja"]
TIPOS = ["estudio", "descanso"]
COLORES = 8                                # índices de la paleta de la pantalla
_candado = threading.RLock()


class ErrorEstudio(ValueError):
    """Dato no válido, explicado en lenguaje simple."""


def _id() -> str:
    return uuid.uuid4().hex[:8]


def _plano(t: str) -> str:
    return " ".join(str(t or "").lower().split())


class PlanEstudio:
    def __init__(self, carpeta: Path):
        self.archivo = carpeta / "estudio.json"

    # ------------------------------------------------------------ almacenamiento

    def cargar(self) -> dict:
        with _candado:
            if not self.archivo.exists():
                return {"materias": [], "bloques": [], "notas": {}}
            datos = json.loads(self.archivo.read_text(encoding="utf-8"))
            datos.setdefault("materias", []), datos.setdefault("bloques", []), datos.setdefault("notas", {})
            return datos

    def guardar(self, datos: dict) -> None:
        with _candado:
            self.archivo.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.archivo.with_suffix(".tmp")
            tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.archivo)

    # ------------------------------------------------------------ utilidades

    @staticmethod
    def fecha(texto, campo="fecha") -> str:
        try:
            return date.fromisoformat(str(texto).strip()).isoformat()
        except ValueError as e:
            raise ErrorEstudio(f"«{campo}» debe tener el formato AAAA-MM-DD (recibí {texto!r}).") from e

    @staticmethod
    def hora(texto, campo) -> str:
        try:
            return datetime.strptime(str(texto).strip(), "%H:%M").strftime("%H:%M")
        except ValueError as e:
            raise ErrorEstudio(f"«{campo}» debe tener el formato HH:MM de 24 h (recibí {texto!r}).") from e

    @staticmethod
    def prioridad(texto, defecto="media") -> str:
        p = _plano(texto) or defecto
        p = {"high": "alta", "medium": "media", "low": "baja", "normal": "media"}.get(p, p)
        if p not in PRIORIDADES:
            raise ErrorEstudio("La prioridad debe ser alta, media o baja.")
        return p

    @staticmethod
    def minutos(b: dict) -> int:
        a, z = datetime.strptime(b["inicio"], "%H:%M"), datetime.strptime(b["fin"], "%H:%M")
        return int((z - a).total_seconds() // 60)

    def materia(self, datos: dict, ref) -> dict:
        ref = str(ref or "").strip()
        for m in datos["materias"]:
            if m["id"] == ref:
                return m
        coinciden = [m for m in datos["materias"] if _plano(m["nombre"]) == _plano(ref) or _plano(m["corto"]) == _plano(ref)]
        if len(coinciden) == 1:
            return coinciden[0]
        nombres = ", ".join(f"«{m['nombre']}» (id={m['id']})" for m in datos["materias"]) or "ninguna todavía"
        raise ErrorEstudio(f"No encontré la materia {ref!r}. Materias: {nombres}. Créala con guardar_materia.")

    def bloque(self, datos: dict, bloque_id: str) -> dict:
        b = next((x for x in datos["bloques"] if x["id"] == str(bloque_id)), None)
        if b is None:
            raise ErrorEstudio(f"No encontré el bloque {bloque_id!r}. Usa ver_plan_estudio para ver los ids.")
        return b

    # ------------------------------------------------------------ materias

    def guardar_materia(self, d: dict) -> tuple[dict, bool]:
        """Crea la materia o actualiza la que tenga ese nombre (o id). Devuelve (materia, era_nueva)."""
        with _candado:
            datos = self.cargar()
            nombre = str(d.get("nombre", "")).strip()[:80]
            if not nombre:
                raise ErrorEstudio("Falta el nombre de la materia.")
            existente = next((m for m in datos["materias"] if m["id"] == nombre or _plano(m["nombre"]) == _plano(nombre)), None)
            m = existente or {"id": _id(), "nombre": nombre, "corto": "", "prioridad": "media", "examen": "", "horas_objetivo": 0,
                              "color": len(datos["materias"]) % COLORES}
            if d.get("nombre_nuevo"):
                m["nombre"] = str(d["nombre_nuevo"]).strip()[:80]
            if d.get("corto") is not None or not m["corto"]:
                m["corto"] = (str(d.get("corto") or "").strip() or m["nombre"])[:18]
            if d.get("prioridad") is not None or existente is None:
                m["prioridad"] = self.prioridad(d.get("prioridad"))
            if "examen" in d:
                m["examen"] = self.fecha(d["examen"], "examen") if d.get("examen") else ""
            if "horas_objetivo" in d:
                try:
                    m["horas_objetivo"] = max(0.0, round(float(d.get("horas_objetivo") or 0), 2))
                except (TypeError, ValueError) as e:
                    raise ErrorEstudio("«horas_objetivo» debe ser un número.") from e
            if existente is None:
                datos["materias"].append(m)
            self.guardar(datos)
            return m, existente is None

    def quitar_materia(self, ref, borrar_bloques: bool) -> tuple[dict, list[dict]]:
        with _candado:
            datos = self.cargar()
            m = self.materia(datos, ref)
            quitados = [b for b in datos["bloques"] if b.get("materia_id") == m["id"]]
            if borrar_bloques:
                datos["bloques"] = [b for b in datos["bloques"] if b.get("materia_id") != m["id"]]
            else:
                for b in quitados:
                    b["materia_id"] = ""
            datos["materias"] = [x for x in datos["materias"] if x["id"] != m["id"]]
            self.guardar(datos)
            return m, (quitados if borrar_bloques else [])

    # ------------------------------------------------------------ bloques

    def _validar_bloque(self, datos: dict, b: dict, base: dict | None = None) -> dict:
        base = base or {}
        tipo = _plano(b.get("tipo", base.get("tipo", "estudio")))
        tipo = "descanso" if tipo in ("descanso", "almuerzo", "pausa", "break") else "estudio"
        fecha = self.fecha(b["fecha"]) if b.get("fecha") else base.get("fecha") or self.fecha(b.get("fecha", ""))
        inicio = self.hora(b["inicio"], "inicio") if b.get("inicio") else base.get("inicio") or self.hora("", "inicio")
        fin = self.hora(b["fin"], "fin") if b.get("fin") else base.get("fin") or self.hora("", "fin")
        if fin <= inicio:
            raise ErrorEstudio(f"El bloque de {inicio} termina antes de empezar ({fin}).")
        materia_id = base.get("materia_id", "")
        if b.get("materia"):
            materia_id = self.materia(datos, b["materia"])["id"]
        elif tipo == "estudio" and not materia_id:
            raise ErrorEstudio("Cada bloque de estudio necesita una materia (usa guardar_materia primero).")
        if tipo == "descanso":
            materia_id = ""
        m = next((x for x in datos["materias"] if x["id"] == materia_id), None)
        prioridad = self.prioridad(b["prioridad"]) if b.get("prioridad") else base.get("prioridad") or (m["prioridad"] if m else "media")
        titulo = str(b.get("titulo") or base.get("titulo") or ("Descanso" if tipo == "descanso" else "Estudio")).strip()[:140]
        return {"fecha": fecha, "inicio": inicio, "fin": fin, "tipo": tipo, "materia_id": materia_id,
                "prioridad": prioridad, "titulo": titulo}

    def cruces(self, datos: dict, fechas: set[str]) -> list[str]:
        avisos = []
        for f in sorted(fechas):
            del_dia = sorted((b for b in datos["bloques"] if b["fecha"] == f), key=lambda b: b["inicio"])
            for a, z in zip(del_dia, del_dia[1:]):
                if z["inicio"] < a["fin"]:
                    avisos.append(f"{f}: «{a['titulo']}» ({a['inicio']}-{a['fin']}) se cruza con «{z['titulo']}» ({z['inicio']}-{z['fin']})")
        return avisos

    def agregar_bloques(self, lista: list, notas: list | None, reemplazar_dias: bool) -> tuple[list[dict], list[dict], list[str]]:
        """Devuelve (bloques_nuevos, bloques_reemplazados, avisos_de_cruce)."""
        with _candado:
            datos = self.cargar()
            nuevos = [{"id": _id(), **self._validar_bloque(datos, b), "hecho": False, "evento_id": ""} for b in (lista or [])]
            if not nuevos and not notas:
                raise ErrorEstudio("No enviaste bloques.")
            fechas = {b["fecha"] for b in nuevos}
            reemplazados = []
            if reemplazar_dias:
                reemplazados = [b for b in datos["bloques"] if b["fecha"] in fechas]
                datos["bloques"] = [b for b in datos["bloques"] if b["fecha"] not in fechas]
            datos["bloques"] += nuevos
            datos["bloques"].sort(key=lambda b: (b["fecha"], b["inicio"]))
            for n in notas or []:
                f = self.fecha(n.get("fecha", ""))
                texto = str(n.get("nota", "")).strip()[:80]
                if texto:
                    datos["notas"][f] = texto
                else:
                    datos["notas"].pop(f, None)
            self.guardar(datos)
            return nuevos, reemplazados, self.cruces(datos, fechas)

    def editar_bloque(self, bloque_id: str, d: dict) -> tuple[dict, dict]:
        """Devuelve (bloque_antes, bloque_despues)."""
        with _candado:
            datos = self.cargar()
            b = self.bloque(datos, bloque_id)
            antes = dict(b)
            if any(k in d for k in ("fecha", "inicio", "fin", "titulo", "materia", "prioridad", "tipo")):
                b.update(self._validar_bloque(datos, {k: v for k, v in d.items() if v not in (None, "")}, base=b))
            if "hecho" in d:
                b["hecho"] = bool(d["hecho"])
            datos["bloques"].sort(key=lambda x: (x["fecha"], x["inicio"]))
            self.guardar(datos)
            return antes, dict(b)

    def poner_evento(self, bloque_id: str, evento_id: str) -> None:
        with _candado:
            datos = self.cargar()
            b = next((x for x in datos["bloques"] if x["id"] == bloque_id), None)
            if b:
                b["evento_id"] = evento_id
                self.guardar(datos)

    def borrar_bloques(self, ids=None, fecha=None, materia=None, todo=False) -> list[dict]:
        with _candado:
            datos = self.cargar()
            if todo:
                quitar = list(datos["bloques"])
            else:
                quitar = datos["bloques"]
                if ids:
                    ids = {str(i) for i in ids}
                    faltan = ids - {b["id"] for b in datos["bloques"]}
                    if faltan:
                        raise ErrorEstudio(f"No encontré estos bloques: {', '.join(sorted(faltan))}.")
                    quitar = [b for b in quitar if b["id"] in ids]
                if fecha:
                    f = self.fecha(fecha)
                    quitar = [b for b in quitar if b["fecha"] == f]
                if materia:
                    mid = self.materia(datos, materia)["id"]
                    quitar = [b for b in quitar if b.get("materia_id") == mid]
                if not (ids or fecha or materia):
                    raise ErrorEstudio("Indica qué borrar: ids, fecha, materia o todo=true.")
            fuera = {b["id"] for b in quitar}
            datos["bloques"] = [b for b in datos["bloques"] if b["id"] not in fuera]
            if todo:
                datos["notas"] = {}
            self.guardar(datos)
            return quitar

    # ------------------------------------------------------------ resumen

    def horas_por_materia(self, datos: dict) -> dict[str, dict]:
        r = {m["id"]: {"plan": 0, "hecho": 0, "bloques": 0} for m in datos["materias"]}
        for b in datos["bloques"]:
            if b["tipo"] == "estudio" and b.get("materia_id") in r:
                x = r[b["materia_id"]]
                x["plan"] += self.minutos(b)
                x["bloques"] += 1
                if b.get("hecho"):
                    x["hecho"] += self.minutos(b)
        return r

    def texto(self, hoy: date, desde: str | None = None, dias_semana=None) -> str:
        """Plan de estudio en texto, para Claude y para el agente de Orga."""
        datos = self.cargar()
        if not datos["materias"] and not datos["bloques"]:
            return "PLAN DE ESTUDIO: vacío (todavía no hay materias ni bloques)."
        horas = self.horas_por_materia(datos)
        fmt = lambda m: f"{m // 60} h {m % 60:02d}" if m % 60 else f"{m // 60} h"
        lineas = ["PLAN DE ESTUDIO — MATERIAS:"]
        for m in sorted(datos["materias"], key=lambda m: PRIORIDADES.index(m["prioridad"])):
            h = horas[m["id"]]
            extra = (f", examen {m['examen']}" if m["examen"] else "") + (f", meta {m['horas_objetivo']:g} h" if m["horas_objetivo"] else "")
            lineas.append(f"- {m['nombre']} («{m['corto']}», prioridad {m['prioridad']}{extra}): {fmt(h['plan'])} planificadas, "
                          f"{fmt(h['hecho'])} hechas (id={m['id']})")
        desde = desde or hoy.isoformat()
        bloques = [b for b in datos["bloques"] if b["fecha"] >= desde]
        nombre = {m["id"]: m["corto"] for m in datos["materias"]}
        lineas.append(f"\nBLOQUES DESDE {desde}:" if bloques else f"\n(No hay bloques desde {desde}.)")
        dia_actual = None
        for b in bloques:
            if b["fecha"] != dia_actual:
                dia_actual = b["fecha"]
                d = date.fromisoformat(dia_actual)
                nota = datos["notas"].get(dia_actual)
                lineas.append(f"## {dia_actual}" + (f" ({dias_semana[d.weekday()]})" if dias_semana else "") + (f" — {nota}" if nota else ""))
            if b["tipo"] == "descanso":
                lineas.append(f"- {b['inicio']}-{b['fin']} {b['titulo']} (descanso, id={b['id']})")
            else:
                lineas.append(f"- {b['inicio']}-{b['fin']} [{nombre.get(b['materia_id'], '?')}] {b['titulo']} · prioridad {b['prioridad']}"
                              + (" ✔ hecho" if b.get("hecho") else "") + (" · en Calendar" if b.get("evento_id") else "") + f" (id={b['id']})")
        pasados = sum(1 for b in datos["bloques"] if b["fecha"] < desde and b["tipo"] == "estudio" and not b.get("hecho"))
        if pasados:
            lineas.append(f"\n({pasados} bloques de días anteriores quedaron sin marcar como hechos.)")
        return "\n".join(lineas)
