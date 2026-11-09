"""Conexión con Google Calendar y Google Tasks."""

from __future__ import annotations

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
                    eventos.append(Evento(
                        id=e["id"],
                        titulo=e.get("summary", "(sin título)"),
                        inicio=inicio,
                        fin=final,
                        todo_el_dia=todo_el_dia,
                        creado_por_organizador=es_principal and privadas.get(ETIQUETA) == "1",
                        calendario=cal["nombre"],
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

    def crear_tarea(self, titulo: str, vence: date | None = None, notas: str = "") -> None:
        lista_id = self.tasks.tasklists().list(maxResults=1).execute()["items"][0]["id"]
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
