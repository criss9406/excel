"""
Rutas del modulo de analisis.

Endpoints:
  GET  /                     Pantalla principal con dropdown de tipo de analisis.
  POST /analizar             Recibe archivo + tipo, ejecuta el service y renderiza
                             la pagina de resultado (HTML).
  GET  /descargar/{token}    Devuelve el Excel del ultimo analisis con ese token.
"""
from __future__ import annotations
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from services import edaService, inventarioService, reporteService


router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# Cache en memoria de resultados:
#   token -> (timestamp, resultado, nombre_archivo, tipo).
# TTL corto (1h) — coherente con la decision "sin DB, datos volatiles".
_CACHE: dict[str, tuple[float, dict, str, str]] = {}
_TTL_SEGUNDOS = 3600
_MAX_ENTRADAS = 20


# Catalogo de analisis disponibles en la UI.
ANALISIS_DISPONIBLES = [
    {"id": "eda", "nombre": "EDA — Analisis exploratorio de datos",
     "descripcion": "Revisa nulos, outliers, formatos, duplicados y cardinalidad."},
    {"id": "inventario", "nombre": "Inventario — riesgo, sobre-stock, ABC y zombis",
     "descripcion": "Detecta productos con riesgo de quiebre, sobre-stock, los clasifica ABC y marca los zombis sin ventas."},
]


def _limpiar_cache():
    """Elimina entradas vencidas o sobrantes. Llamado oportunisticamente."""
    ahora = time.time()
    expirados = [k for k, entrada in _CACHE.items() if ahora - entrada[0] > _TTL_SEGUNDOS]
    for k in expirados:
        _CACHE.pop(k, None)
    if len(_CACHE) > _MAX_ENTRADAS:
        # Botar las mas antiguas
        ordenados = sorted(_CACHE.items(), key=lambda kv: kv[1][0])
        for k, _ in ordenados[: len(_CACHE) - _MAX_ENTRADAS]:
            _CACHE.pop(k, None)


# Filtros Jinja2 -------------------------------------------------------------

def _fmt_int(v):
    try:
        return f"{int(v):,}".replace(",", ".")
    except (TypeError, ValueError):
        return v


def _fmt_porcentaje(parte, total):
    try:
        if total == 0:
            return "0%"
        return f"{(parte / total) * 100:.1f}%"
    except (TypeError, ZeroDivisionError):
        return "—"


def _fmt_moneda(v):
    """Formato monetario amigable (sin sigla, agrupador punto, 0 decimales)."""
    try:
        return f"{float(v):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return v


templates.env.filters["fmt_int"] = _fmt_int
templates.env.filters["fmt_pct"] = _fmt_porcentaje
templates.env.filters["fmt_moneda"] = _fmt_moneda


# Endpoints ------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Pantalla principal con dropdown de tipo de analisis y subida de archivo."""
    return templates.TemplateResponse(
        request,
        "analisis/index.html",
        {"analisis_disponibles": ANALISIS_DISPONIBLES},
    )


@router.post("/analizar", response_class=HTMLResponse)
async def analizar(
    request: Request,
    archivo: UploadFile = File(...),
    tipo: str = Form(...),
    lead_time_dias: int = Form(7),
    margen_pct: float = Form(30.0),
    dias_zombi: int = Form(60),
    factor_sobrestock: float = Form(4.0),
):
    """Procesa el archivo segun el tipo seleccionado y muestra el resultado."""
    if tipo not in {a["id"] for a in ANALISIS_DISPONIBLES}:
        raise HTTPException(400, f"Tipo de analisis desconocido: {tipo}")

    nombre = archivo.filename or "archivo"
    if not nombre.lower().endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(400, "Formato no soportado. Use .xlsx, .xls o .csv")

    contenido = await archivo.read()
    if not contenido:
        raise HTTPException(400, "El archivo esta vacio")

    if tipo == "eda":
        try:
            resultado = edaService.analizar(contenido, nombre)
        except Exception as e:
            raise HTTPException(400, f"No se pudo procesar el archivo: {e}")
    elif tipo == "inventario":
        try:
            resultado = inventarioService.analizar(
                contenido, nombre,
                lead_time_dias=lead_time_dias,
                margen_pct=margen_pct,
                dias_zombi=dias_zombi,
                factor_sobrestock=factor_sobrestock,
            )
        except Exception as e:
            raise HTTPException(400, f"No se pudo procesar el archivo: {e}")
    else:
        raise HTTPException(400, f"Tipo no implementado: {tipo}")

    _limpiar_cache()
    token = uuid.uuid4().hex
    _CACHE[token] = (time.time(), resultado, nombre, tipo)

    analisis_meta = next(a for a in ANALISIS_DISPONIBLES if a["id"] == tipo)

    return templates.TemplateResponse(
        request,
        "analisis/resultado.html",
        {
            "resultado": resultado,
            "token": token,
            "analisis": analisis_meta,
        },
    )


@router.get("/descargar/{token}")
async def descargar(token: str):
    """Devuelve el Excel del analisis identificado por token."""
    entrada = _CACHE.get(token)
    if not entrada:
        raise HTTPException(404, "Reporte no disponible (expirado o inexistente)")
    _, resultado, nombre_archivo, tipo = entrada
    bytes_excel = reporteService.generar_excel(resultado)

    nombre_base = Path(nombre_archivo).stem
    nombre_salida = f"reporte_{tipo}_{nombre_base}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{nombre_salida}"'}
    return StreamingResponse(
        iter([bytes_excel]),
        headers=headers,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
