"""Conexión con Google Calendar y Google Tasks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import Config

# Permisos que pide la app: leer/escribir eventos y tareas.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks",
]

# Marca para reconocer los bloques creados por el Organizador.
ETIQUETA = "organizador"


@dataclass
class Evento:
    id: str
    titulo: str
    inicio: datetime
    fin: datetime
    todo_el_dia: bool
    creado_por_organizador: bool
    calendario: str = ""
    calendario_id: str = ""


@dataclass
class Tarea:
    id: str
    lista_id: str
    lista: str
    titulo: str
    notas: str
    vence: date | None


def obtener_credenciales(cfg: Config) -> Credentials:
    """Abre el navegador la primera vez para iniciar sesión en Google; luego reutiliza token.json."""
    creds = None
    if cfg.archivo_token.exists():
        creds = Credentials.from_authorized_user_file(str(cfg.archivo_token), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not cfg.archivo_credenciales.exists():
            raise FileNotFoundError(
                f"No encontré {cfg.archivo_credenciales.name}. "
                "Descárgalo de Google Cloud Console (ver README.md, paso 2)."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(cfg.archivo_credenciales), SCOPES)
        creds = flow.run_local_server(port=0)
    cfg.archivo_token.write_text(creds.to_json())
    return creds


class Google:
    def __init__(self, cfg: Config, creds: Credentials | None = None):
        self.cfg = cfg
        if creds is None:
            creds = obtener_credenciales(cfg)
        self.calendar = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self.tasks = build("tasks", "v1", credentials=creds, cache_discovery=False)

    # ---------- Calendar ----------

    def calendarios(self) -> list[dict]:
        """Todos los calendarios que tienes visibles (CLASES, ESTUDIO, Family, etc.)."""
        if not hasattr(self, "_calendarios"):
            items = self.calendar.calendarList().list(minAccessRole="reader").execute().get("items", [])
            self._calendarios = [
                {"id": c["id"], "nombre": c.get("summaryOverride") or c.get("summary", ""), "principal": c.get("primary", False)}
                for c in items
                if c.get("selected", True) and not c.get("hidden", False)
            ]
            # CALENDARIOS="a,b": leer solo esos calendarios (por nombre o id, sin importar mayúsculas)
            filtro = [f.strip().lower() for f in os.getenv("CALENDARIOS", "").split(",") if f.strip()]
            if filtro:
                for c in self._calendarios:
                    c["solo_bloques"] = not any(f in c["id"].lower() or f in c["nombre"].lower() for f in filtro)
                # Del resto solo se mantiene el principal, y únicamente para ver los bloques del Organizador
                self._calendarios = [c for c in self._calendarios if not c["solo_bloques"] or c["principal"]]
            if not any(c["id"] == self.cfg.calendario_id or (c["principal"] and self.cfg.calendario_id == "primary")
                       for c in self._calendarios):
                self._calendarios.append({"id": self.cfg.calendario_id, "nombre": "Principal", "principal": True})
        return self._calendarios

    def eventos_entre(self, desde: date, hasta: date) -> list[Evento]:
        """Eventos de todos tus calendarios entre dos fechas (hasta no incluida)."""
        zona = self.cfg.zona
        t_min = datetime.combine(desde, time.min, zona).isoformat()
        t_max = datetime.combine(hasta, time.min, zona).isoformat()
        eventos: list[Evento] = []
        for cal in self.calendarios():
            token = None
            while True:
                resp = (
                    self.calendar.events()
                    .list(calendarId=cal["id"], timeMin=t_min, timeMax=t_max, singleEvents=True,
                          orderBy="startTime", maxResults=250, pageToken=token)
                    .execute()
                )
                for e in resp.get("items", []):
                    if e.get("status") == "cancelled":
                        continue
                    ini, fin = e["start"], e["end"]
                    todo_el_dia = "date" in ini
                    if todo_el_dia:
                        inicio = datetime.combine(date.fromisoformat(ini["date"]), time.min, zona)
                        final = datetime.combine(date.fromisoformat(fin["date"]), time.min, zona)
                    else:
                        inicio = datetime.fromisoformat(ini["dateTime"]).astimezone(zona)
                        final = datetime.fromisoformat(fin["dateTime"]).astimezone(zona)
                    privadas = e.get("extendedProperties", {}).get("private", {})
                    es_principal = cal["principal"] or cal["id"] == self.cfg.calendario_id
                    if cal.get("solo_bloques") and privadas.get(ETIQUETA) != "1":
                        continue
                    eventos.append(Evento(
                        id=e["id"],
                        titulo=e.get("summary", "(sin título)"),
                        inicio=inicio,
                        fin=final,
                        todo_el_dia=todo_el_dia,
                        creado_por_organizador=es_principal and privadas.get(ETIQUETA) == "1",
                        calendario=cal["nombre"],
                        calendario_id=cal["id"],
                    ))
                token = resp.get("nextPageToken")
                if not token:
                    break
        eventos.sort(key=lambda e: (not e.todo_el_dia, e.inicio))
        return eventos

    def eventos_del_dia(self, dia: date) -> list[Evento]:
        return self.eventos_entre(dia, dia + timedelta(days=1))

    def eventos_rango(self, desde: date, dias: int) -> dict[date, list[Evento]]:
        todos = self.eventos_entre(desde, desde + timedelta(days=dias))
        zona = self.cfg.zona
        por_dia: dict[date, list[Evento]] = {}
        for i in range(dias):
            d = desde + timedelta(days=i)
            ini_d = datetime.combine(d, time.min, zona)
            fin_d = ini_d + timedelta(days=1)
            por_dia[d] = [e for e in todos if e.inicio < fin_d and e.fin > ini_d]
        return por_dia

    def borrar_evento_organizador(self, evento_id: str) -> bool:
        """Borra un evento solo si lo creó el Organizador (nunca toca tus eventos propios)."""
        e = self.calendar.events().get(calendarId=self.cfg.calendario_id, eventId=evento_id).execute()
        if e.get("extendedProperties", {}).get("private", {}).get(ETIQUETA) != "1":
            return False
        self.calendar.events().delete(calendarId=self.cfg.calendario_id, eventId=evento_id).execute()
        return True

    def _ubicar_evento(self, evento_id: str) -> tuple[str, dict]:
        """Busca un evento por id en tus calendarios. Devuelve (calendario_id, evento)."""
        from googleapiclient.errors import HttpError
        for cal in [{"id": self.cfg.calendario_id}] + self.calendarios():
            try:
                return cal["id"], self.calendar.events().get(calendarId=cal["id"], eventId=evento_id).execute()
            except HttpError as e:
                if e.status_code not in (400, 404, 410):
                    raise
        raise LookupError(evento_id)

    def editar_evento(self, evento_id: str, titulo: str | None = None, inicio: datetime | None = None,
                      fin: datetime | None = None, descripcion: str | None = None) -> dict:
        """Cambia título, horario o descripción de un evento de cualquiera de tus calendarios."""
        cal_id, e = self._ubicar_evento(evento_id)
        cuerpo: dict = {}
        if titulo is not None:
            cuerpo["summary"] = titulo
        if descripcion is not None:
            cuerpo["description"] = descripcion
        if inicio is not None or fin is not None:
            if "dateTime" in e["start"]:
                ini_actual = datetime.fromisoformat(e["start"]["dateTime"]).astimezone(self.cfg.zona)
                fin_actual = datetime.fromisoformat(e["end"]["dateTime"]).astimezone(self.cfg.zona)
            else:
                ini_actual = datetime.combine(date.fromisoformat(e["start"]["date"]), time(9), self.cfg.zona)
                fin_actual = ini_actual + timedelta(hours=1)
            nuevo_ini = inicio or ini_actual
            nuevo_fin = fin or (nuevo_ini + (fin_actual - ini_actual))
            if nuevo_fin <= nuevo_ini:
                raise ValueError("La hora de fin debe ser después de la de inicio.")
            cuerpo["start"] = {"dateTime": nuevo_ini.isoformat(), "timeZone": str(self.cfg.zona)}
            cuerpo["end"] = {"dateTime": nuevo_fin.isoformat(), "timeZone": str(self.cfg.zona)}
        return self.calendar.events().patch(calendarId=cal_id, eventId=evento_id, body=cuerpo).execute()

    def borrar_evento(self, evento_id: str) -> str:
        """Borra un evento de cualquiera de tus calendarios. Devuelve su título."""
        cal_id, e = self._ubicar_evento(evento_id)
        self.calendar.events().delete(calendarId=cal_id, eventId=evento_id).execute()
        return e.get("summary", "(sin título)")

    def es_bloque_organizador(self, evento_id: str) -> bool:
        try:
            _, e = self._ubicar_evento(evento_id)
        except LookupError:
            return False
        return e.get("extendedProperties", {}).get("private", {}).get(ETIQUETA) == "1"

    def crear_bloque(self, titulo: str, inicio: datetime, fin: datetime, descripcion: str = "") -> str:
        cuerpo = {
            "summary": titulo,
            "description": descripcion,
            "start": {"dateTime": inicio.isoformat(), "timeZone": str(self.cfg.zona)},
            "end": {"dateTime": fin.isoformat(), "timeZone": str(self.cfg.zona)},
            "colorId": "9",  # azul oscuro
            "extendedProperties": {"private": {ETIQUETA: "1"}},
        }
        evento = self.calendar.events().insert(calendarId=self.cfg.calendario_id, body=cuerpo).execute()
        return evento["id"]

    def borrar_bloques_del_organizador(self, dia: date) -> int:
        """Borra los bloques que el Organizador creó ese día (para re-planificar)."""
        borrados = 0
        for e in self.eventos_del_dia(dia):
            if e.creado_por_organizador:
                self.calendar.events().delete(calendarId=self.cfg.calendario_id, eventId=e.id).execute()
                borrados += 1
        return borrados

    # ---------- Tasks ----------

    def tareas_pendientes(self) -> list[Tarea]:
        tareas: list[Tarea] = []
        listas = self.tasks.tasklists().list(maxResults=100).execute().get("items", [])
        for lista in listas:
            token = None
            while True:
                resp = (
                    self.tasks.tasks()
                    .list(tasklist=lista["id"], showCompleted=False, maxResults=100, pageToken=token)
                    .execute()
                )
                for t in resp.get("items", []):
                    titulo = (t.get("title") or "").strip()
                    if not titulo:
                        continue
                    vence = date.fromisoformat(t["due"][:10]) if t.get("due") else None
                    tareas.append(
                        Tarea(
                            id=t["id"],
                            lista_id=lista["id"],
                            lista=lista.get("title", ""),
                            titulo=titulo,
                            notas=t.get("notes", ""),
                            vence=vence,
                        )
                    )
                token = resp.get("nextPageToken")
                if not token:
                    break
        return tareas

    def completar_tarea(self, tarea: Tarea) -> None:
        self.completar_tarea_id(tarea.lista_id, tarea.id)

    def completar_tarea_id(self, lista_id: str, tarea_id: str) -> None:
        self.tasks.tasks().patch(
            tasklist=lista_id, task=tarea_id, body={"status": "completed"}
        ).execute()

    def cambiar_fecha_tarea(self, lista_id: str, tarea_id: str, fecha: date | None) -> None:
        due = f"{fecha.isoformat()}T00:00:00.000Z" if fecha else None
        self.tasks.tasks().patch(tasklist=lista_id, task=tarea_id, body={"due": due}).execute()

    def tareas_completadas_hoy(self, dia: date) -> list[str]:
        """Títulos de las tareas que marcaste como completadas ese día."""
        desde = datetime.combine(dia, time.min, self.cfg.zona)
        titulos: list[str] = []
        listas = self.tasks.tasklists().list(maxResults=100).execute().get("items", [])
        for lista in listas:
            resp = (
                self.tasks.tasks()
                .list(
                    tasklist=lista["id"],
                    showCompleted=True,
                    showHidden=True,
                    completedMin=desde.isoformat(),
                    maxResults=100,
                )
                .execute()
            )
            for t in resp.get("items", []):
                if t.get("status") == "completed" and (t.get("title") or "").strip():
                    titulos.append(t["title"].strip())
        return titulos

    # ---------- Proyectos (listas de Google Tasks) ----------

    def listas(self) -> list[dict]:
        items = self.tasks.tasklists().list(maxResults=100).execute().get("items", [])
        return [{"id": l["id"], "nombre": l.get("title", "")} for l in items]

    def crear_lista(self, nombre: str) -> dict:
        l = self.tasks.tasklists().insert(body={"title": nombre}).execute()
        return {"id": l["id"], "nombre": l.get("title", "")}

    def renombrar_lista(self, lista_id: str, nombre: str) -> None:
        self.tasks.tasklists().patch(tasklist=lista_id, body={"title": nombre}).execute()

    def borrar_lista(self, lista_id: str) -> None:
        self.tasks.tasklists().delete(tasklist=lista_id).execute()

    def editar_tarea(self, lista_id: str, tarea_id: str, titulo: str | None = None, notas: str | None = None) -> None:
        cuerpo = {k: v for k, v in (("title", titulo), ("notes", notas)) if v is not None}
        if cuerpo:
            self.tasks.tasks().patch(tasklist=lista_id, task=tarea_id, body=cuerpo).execute()

    def borrar_tarea(self, lista_id: str, tarea_id: str) -> None:
        self.tasks.tasks().delete(tasklist=lista_id, task=tarea_id).execute()

    def reabrir_tarea(self, lista_id: str, tarea_id: str) -> None:
        self.tasks.tasks().patch(tasklist=lista_id, task=tarea_id, body={"status": "needsAction", "completed": None}).execute()

    def tareas_completadas(self, dias: int = 14) -> list[Tarea]:
        """Tareas completadas en los últimos días (para poder reabrirlas)."""
        desde = datetime.combine(datetime.now(self.cfg.zona).date() - timedelta(days=dias), time.min, self.cfg.zona)
        salida = []
        for l in self.listas():
            resp = self.tasks.tasks().list(tasklist=l["id"], showCompleted=True, showHidden=True,
                                           completedMin=desde.isoformat(), maxResults=100).execute()
            for t in resp.get("items", []):
                if t.get("status") == "completed" and (t.get("title") or "").strip():
                    salida.append(Tarea(t["id"], l["id"], l["nombre"], t["title"].strip(), t.get("notes", ""),
                                        date.fromisoformat(t["due"][:10]) if t.get("due") else None))
        return salida

    def mover_tarea(self, lista_id: str, tarea_id: str, lista_destino: str) -> None:
        """Pasa una tarea a otro proyecto (lista), conservando título, notas y fecha."""
        t = self.tasks.tasks().get(tasklist=lista_id, task=tarea_id).execute()
        cuerpo = {k: t[k] for k in ("title", "notes", "due") if t.get(k)}
        self.tasks.tasks().insert(tasklist=lista_destino, body=cuerpo).execute()
        self.tasks.tasks().delete(tasklist=lista_id, task=tarea_id).execute()

    def crear_tarea(self, titulo: str, vence: date | None = None, notas: str = "", lista_id: str | None = None) -> None:
        lista_id = lista_id or self.tasks.tasklists().list(maxResults=1).execute()["items"][0]["id"]
        cuerpo = {"title": titulo, "notes": notas}
        if vence:
            cuerpo["due"] = f"{vence.isoformat()}T00:00:00.000Z"
        self.tasks.tasks().insert(tasklist=lista_id, body=cuerpo).execute()


def huecos_libres(eventos: list[Evento], dia: date, cfg: Config, desde: datetime | None = None):
    """Calcula los espacios libres entre eventos dentro del horario de trabajo."""
    zona = cfg.zona
    inicio = datetime.combine(dia, cfg.hora_inicio, zona)
    fin = datetime.combine(dia, cfg.hora_fin, zona)
    if desde and desde > inicio:
        # Redondear al siguiente cuarto de hora
        minutos = (15 - desde.minute % 15) % 15
        inicio = (desde + timedelta(minutes=minutos)).replace(second=0, microsecond=0)
    ocupados = sorted(
        (e.inicio, e.fin) for e in eventos if not e.todo_el_dia and not e.creado_por_organizador
    )
    huecos = []
    cursor = inicio
    for a, b in ocupados:
        if b <= cursor:
            continue
        if a > cursor:
            huecos.append((cursor, min(a, fin)))
        cursor = max(cursor, b)
        if cursor >= fin:
            break
    if cursor < fin:
        huecos.append((cursor, fin))
    return [(a, b) for a, b in huecos if (b - a) >= timedelta(minutes=15)]
