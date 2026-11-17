"""ColegioFinanzas OS — lectura del libro de Excel del colegio guardado en OneDrive.

Descarga el archivo desde su enlace para compartir y convierte las hojas de gastos e ingresos
en movimientos. Si una fila no tiene fecha, toma la fecha inmediata anterior de esa hoja.
"""

from __future__ import annotations

import io
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime
from http.cookiejar import CookieJar
from urllib.parse import urlparse

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Setiembre", "Octubre", "Noviembre", "Diciembre"]
TAMANO_MAXIMO = 15 * 1024 * 1024
NAVEGADOR = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

CAT_INGRESO = "Pensiones"
CAT_OTROS = "Pagos a personas y otros"
# Se revisan en orden: la primera regla que coincide con el concepto decide la categoría.
REGLAS_GASTO = [
    ("Servicios, impuestos y trámites", r"\b(luz|agua|internet|gas|telefono|celular|sunat|sumat|municip\w*|munici\w*|muni|siagie|ugel\w*|contador|fraccionamiento|arbitrios|predial)\b"),
    ("Alimentación y cocina", r"(cocin|cocni|cocia|almuerz|almuez|cena\b|desayun|desyun|lonche|menu|gaseosa|tamal|fruta|compras|pollada|polleria|poilleria|pescado|\bcuy\b|cerveza|vino|chancho|golosina|compartir|viveres|mercado|pan\b|queso|pollo|arroz|azucar|leche|comida|carne|verdura)"),
    ("Transporte y movilidad", r"(gasolina|peaje|movilidad|pasaje|\bvan\b|carro|aceite|frenos|taxi|combustible|blanquita)"),
    ("Mantenimiento y materiales", r"(arregl|aregl|pintur|pinutr|sillas|carpeta|impresora|proyector|mayolica|inodoro|libros|material|limpieza|fumig|extintor|repisa|gras\b|toldo|mobiliario|moviliario|water|escenario|gigantografia|utiles|detergente|copias|plastico)"),
]


class ErrorExcel(Exception):
    """Problema que se le puede explicar a Dirección tal cual."""


# ---------------------------------------------------------------- descarga


def _dominio_permitido(host: str) -> bool:
    host = (host or "").lower()
    return host in ("1drv.ms", "onedrive.live.com") or host.endswith(
        (".sharepoint.com", ".onedrive.com", ".1drv.com", ".live.com", ".microsoftpersonalcontent.com"))


def revisar_enlace(enlace: str) -> str | None:
    p = urlparse(enlace)
    if p.scheme != "https" or not p.hostname:
        return "El enlace debe empezar con https://"
    if not _dominio_permitido(p.hostname):
        return "Pega el enlace de «Compartir» de tu Excel en OneDrive (empieza con https://1drv.ms/…)."
    return None


class _SoloOneDrive(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urlparse(newurl)
        if p.scheme != "https" or not _dominio_permitido(p.hostname):
            raise ErrorExcel("El enlace llevó a un sitio que no es OneDrive.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def descargar(enlace: str) -> bytes:
    """Baja el .xlsx de un enlace de OneDrive compartido como «cualquier persona con el vínculo»."""
    problema = revisar_enlace(enlace)
    if problema:
        raise ErrorExcel(problema)
    url = enlace + ("&" if "?" in enlace else "?") + "download=1"
    abridor = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()), _SoloOneDrive())
    try:
        with abridor.open(urllib.request.Request(url, headers={"User-Agent": NAVEGADOR}), timeout=40) as r:
            contenido = r.read(TAMANO_MAXIMO + 1)
    except ErrorExcel:
        raise
    except urllib.error.HTTPError as e:
        raise ErrorExcel(f"OneDrive respondió con error {e.code}. Revisa que el enlace siga compartido.") from e
    except Exception as e:
        raise ErrorExcel(f"No se pudo conectar con OneDrive ({type(e).__name__}).") from e
    if len(contenido) > TAMANO_MAXIMO:
        raise ErrorExcel("El archivo pesa más de 15 MB.")
    if not contenido.startswith(b"PK"):
        raise ErrorExcel("OneDrive no entregó el archivo. Compártelo como «Cualquier persona que tenga el vínculo puede ver».")
    return contenido


# ---------------------------------------------------------------- lectura


def _plano(texto) -> str:
    s = unicodedata.normalize("NFD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def _monto(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    s = s.replace(",", "")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _fecha(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        m = re.match(r"\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\s*$", v)
        if m:
            d, mes, a = (int(x) for x in m.groups())
            try:
                return date(a + 2000 if a < 100 else a, mes, d)
            except ValueError:
                return None
    return None


def _texto(v) -> str:
    return " ".join(str(v).split()) if v is not None else ""


def categoria_gasto(concepto: str) -> str:
    plano = _plano(concepto)
    for categoria, patron in REGLAS_GASTO:
        if re.search(patron, plano):
            return categoria
    return CAT_OTROS


def _medio(valor: str) -> str:
    v = _plano(valor).upper()
    if "BCP" in v:
        return "BCP"
    if "BBV" in v:
        return "BBVA"
    if v.startswith("EFE"):
        return "Efectivo"
    if "YAPE" in v or "PLIN" in v:
        return "Yape / Plin"
    return _texto(valor)[:30] or "Sin especificar"


def _columnas(encabezados: list, reglas: dict) -> dict:
    """Ubica cada columna por el texto de su encabezado (la primera que coincide)."""
    cols = {}
    for i, titulo in enumerate(encabezados):
        t = _plano(titulo)
        for clave, palabras in reglas.items():
            if clave not in cols and t and any(p in t for p in palabras):
                cols[clave] = i
                break
    return cols


def leer(contenido: bytes) -> tuple[list[dict], dict]:
    """Devuelve (movimientos, resumen) a partir del libro. No modifica el archivo."""
    try:
        from openpyxl import load_workbook
        libro = load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
    except Exception as e:
        raise ErrorExcel("No pude abrir el archivo: ¿es un Excel (.xlsx)?") from e

    tx: list[dict] = []
    info = {"hojas": [], "ingresos": 0, "gastos": 0, "totalIngresos": 0.0, "totalGastos": 0.0,
            "fechasCompletadas": 0, "omitidas": 0}

    for n, hoja in enumerate(libro.worksheets):
        titulo = _plano(hoja.title)
        tipo = "gasto" if "gasto" in titulo else "ingreso" if "ingreso" in titulo else None
        if tipo is None:
            continue
        filas = hoja.iter_rows(values_only=True)
        encabezados = list(next(filas, ()) or ())
        if tipo == "gasto":
            cols = _columnas(encabezados, {"fecha": ["fecha"], "monto": ["monto", "importe"], "concepto": ["gasto", "concepto", "detalle", "descripcion"]})
        else:
            cols = _columnas(encabezados, {"fecha": ["fecha"], "monto": ["importe", "monto"], "nombre": ["nombre", "alumno"],
                                           "medio": ["tipo"], "grado": ["grado"], "mes": ["mes"]})
        if "fecha" not in cols or "monto" not in cols:
            continue

        def celda(fila, clave):
            i = cols.get(clave)
            return fila[i] if i is not None and i < len(fila) else None

        usadas = set(cols.values())
        ultima: date | None = None
        cuenta = 0
        for numero, fila in enumerate(filas, start=2):
            if not fila or all(v is None for v in fila):
                continue
            propia = _fecha(celda(fila, "fecha"))
            if propia:
                ultima = propia
            monto = _monto(celda(fila, "monto"))
            if monto is None:
                continue                                   # fila sin importe: separador o nota
            if monto <= 0 or ultima is None:
                info["omitidas"] += 1                      # importe en cero, o aún no apareció ninguna fecha
                continue
            if propia is None:
                info["fechasCompletadas"] += 1             # regla: usar la fecha inmediata anterior
            if tipo == "gasto":
                concepto = _texto(celda(fila, "concepto"))
                categoria, medio, operacion = categoria_gasto(concepto), "Sin especificar", ""
            else:
                partes = [_texto(celda(fila, c)) for c in ("nombre", "grado", "mes")]
                notas = [_texto(v) for i, v in enumerate(fila) if i not in usadas and isinstance(v, str) and v.strip()]
                concepto = " · ".join(p for p in partes + notas if p)
                crudo = _texto(celda(fila, "medio"))
                categoria, medio = CAT_INGRESO, _medio(crudo)
                operacion = crudo if crudo.upper() != medio.upper() else ""
            tx.append({
                "id": f"x{tipo[0]}{n}-{numero}", "fecha": ultima.isoformat(), "hora": "00:00:00",
                "semana": ultima.isocalendar()[1], "mes": MESES[ultima.month - 1], "tipo": tipo,
                "categoria": categoria, "concepto": concepto[:120], "monto": monto, "metodoPago": medio,
                "nOperacion": operacion[:40], "registradoPor": "Excel", "userId": None,
                "sync": "excel", "origen": "excel", "fila": numero, "hoja": hoja.title.strip(),
            })
            cuenta += 1
            info["ingresos" if tipo == "ingreso" else "gastos"] += 1
            info["totalIngresos" if tipo == "ingreso" else "totalGastos"] += monto
        info["hojas"].append({"nombre": hoja.title.strip(), "tipo": tipo, "filas": cuenta})

    if not info["hojas"]:
        raise ErrorExcel("No encontré hojas de «GASTOS» o «INGRESOS» con columnas FECHA y MONTO/IMPORTE.")
    info["totalIngresos"], info["totalGastos"] = round(info["totalIngresos"], 2), round(info["totalGastos"], 2)
    tx.sort(key=lambda t: (t["fecha"], t["tipo"], t["fila"]))
    return tx, info
