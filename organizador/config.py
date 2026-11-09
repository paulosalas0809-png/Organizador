"""Configuración leída desde el archivo .env."""

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")


def _hora(texto: str) -> time:
    h, m = texto.strip().split(":")
    return time(int(h), int(m))


@dataclass(frozen=True)
class Config:
    zona: ZoneInfo
    hora_inicio: time
    hora_fin: time
    calendario_id: str
    archivo_credenciales: Path
    archivo_token: Path
    carpeta_datos: Path


def cargar_config() -> Config:
    return Config(
        zona=ZoneInfo(os.getenv("ZONA_HORARIA", "America/Mexico_City")),
        hora_inicio=_hora(os.getenv("HORA_INICIO", "08:00")),
        hora_fin=_hora(os.getenv("HORA_FIN", "20:00")),
        calendario_id=os.getenv("CALENDARIO_ID", "primary"),
        archivo_credenciales=RAIZ / "credentials.json",
        archivo_token=RAIZ / "token.json",
        # En el servidor (Railway) apunta a un volumen persistente, p. ej. /data
        carpeta_datos=Path(os.getenv("CARPETA_DATOS", str(RAIZ / "datos"))),
    )
