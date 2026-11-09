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
    def __init__(self, cfg: Config):
        self.cfg = cfg
        creds = obtener_credenciales(cfg)
        self.calendar = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self.tasks = build("tasks", "v1", credentials=creds, cache_discovery=False)

    # ---------- Calendar ----------

    def eventos_del_dia(self, dia: date) -> list[Evento]:
        zona = self.cfg.zona
        desde = datetime.combine(dia, time.min, zona)
        hasta = desde + timedelta(days=1)
        resp = (
            self.calendar.events()
            .list(
                calendarId=self.cfg.calendario_id,
                timeMin=desde.isoformat(),
                timeMax=hasta.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        eventos = []
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
            eventos.append(
                Evento(
                    id=e["id"],
                    titulo=e.get("summary", "(sin título)"),
                    inicio=inicio,
                    fin=final,
                    todo_el_dia=todo_el_dia,
                    creado_por_organizador=privadas.get(ETIQUETA) == "1",
                )
            )
        return eventos

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
        return evento.get("htmlLink", "")

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
        self.tasks.tasks().patch(
            tasklist=tarea.lista_id, task=tarea.id, body={"status": "completed"}
        ).execute()

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
