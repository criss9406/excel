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
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
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
    {"id": "eda", "nombre": "EDA — Análisis exploratorio de datos", "descripcion": "Revisa nulos, outliers, formatos, duplicados y cardinalidad."},
    {"id": "inventario", "nombre": "Análisis de Inventario", "descripcion": "Detecta productos con riesgo de quiebre, sobre-stock, los clasifica ABC y marca los zombis."},
    {"id": "copy_paste", "nombre": "Copy-paste Diario (Anexar datos)", "descripcion": "Extrae filas de un reporte diario y las anexa automáticamente al reporte maestro histórico."},
    {"id": "limpieza", "nombre": "Limpieza de Datos Sucios", "descripcion": "Estandariza formatos de fecha y números, y elimina filas duplicadas de una exportación cruda."},
    {"id": "reporte_recurrente", "nombre": "Reporte Recurrente Automático", "descripcion": "Aplica formato y transformaciones estandarizadas a los datos crudos del mes."},
    {"id": "consolidacion", "nombre": "Consolidación de Múltiples Archivos", "descripcion": "Une varios archivos idénticos (ej. sucursales) en una tabla única con origen."},
    {"id": "reconciliacion", "nombre": "Reconciliación Manual (Cruce)", "descripcion": "Cruza una cartola bancaria con un libro mayor para encontrar diferencias y partidas pendientes."},
    {"id": "pdf_to_excel", "nombre": "Extracción PDF a Excel", "descripcion": "Lee la tabla principal de un reporte en PDF y la exporta directamente a Excel limpio."},
    {"id": "cobranzas", "nombre": "Seguimiento de Cobranzas", "descripcion": "Calcula mora por cliente y clasifica el estado para habilitar alertas automáticas."},
    {"id": "generacion_doc", "nombre": "Generación de Documentos (Zip)", "descripcion": "Lee un Excel y genera un lote de reportes (TXT/CSV) emulando plantillas masivas de contratos o facturas."},
    {"id": "carga_erp", "nombre": "Preparación Carga a ERP", "descripcion": "Valida un Excel contra reglas de negocio y genera un log de validación estructurado listo para RPA."},
    {"id": "reporte_rrhh", "nombre": "Reporte RRHH (Reloj Control)", "descripcion": "Pivotea marcas de entrada/salida y resume horas totales por empleado para la plantilla oficial."},
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


@router.post("/api/analizar")
async def analizar(
    request: Request,
    archivos: list[UploadFile] = File(...),
    tipo: str = Form(...),
    lead_time_dias: int = Form(7),
    margen_pct: float = Form(30.0),
    dias_zombi: int = Form(60),
    factor_sobrestock: float = Form(4.0),
):
    """Procesa el archivo segun el tipo seleccionado y muestra el resultado."""
    if tipo not in {a["id"] for a in ANALISIS_DISPONIBLES}:
        raise HTTPException(400, f"Tipo de analisis desconocido: {tipo}")

    if not archivos:
        raise HTTPException(400, "Debe seleccionar al menos un archivo")

    # Tomar el primer archivo para los flujos que asumen uno solo
    archivo = archivos[0]
    nombre = archivo.filename or "archivo"
    
    # Importar servicios de automatizacion aqui para evitar ciclos
    from services.automations import (
        data_cleaning, 
        consolidation_reconciliation, 
        document_processing, 
        workflow_automation
    )

    contenido = await archivo.read()
    if not contenido:
        raise HTTPException(400, "El archivo esta vacio")

    resultado = None
    try:
        if tipo == "eda":
            resultado = edaService.analizar(contenido, nombre)
        elif tipo == "inventario":
            resultado = inventarioService.analizar(
                contenido, nombre, lead_time_dias=lead_time_dias, margen_pct=margen_pct,
                dias_zombi=dias_zombi, factor_sobrestock=factor_sobrestock
            )
        elif tipo == "copy_paste":
            if len(archivos) < 2: raise HTTPException(400, "Se requieren 2 archivos para Copy-Paste Diario (Maestro y Diario).")
            c1, c2 = contenido, await archivos[1].read()
            resultado = data_cleaning.procesar_copy_paste(c1, c2, archivos[0].filename, archivos[1].filename)
        elif tipo == "limpieza":
            resultado = data_cleaning.procesar_limpieza(contenido, nombre)
        elif tipo == "reporte_recurrente":
            resultado = data_cleaning.procesar_recurrente(contenido, nombre)
        elif tipo == "consolidacion":
            if len(archivos) < 2: raise HTTPException(400, "Seleccione múltiples archivos para consolidar.")
            conts = [contenido] + [await a.read() for a in archivos[1:]]
            nombres = [a.filename for a in archivos]
            resultado = consolidation_reconciliation.procesar_consolidacion(conts, nombres)
        elif tipo == "reconciliacion":
            if len(archivos) < 2: raise HTTPException(400, "Se requieren 2 archivos (Cartola y Libro Mayor).")
            c1, c2 = contenido, await archivos[1].read()
            resultado = consolidation_reconciliation.procesar_reconciliacion(c1, c2, archivos[0].filename, archivos[1].filename)
        elif tipo == "pdf_to_excel":
            resultado = document_processing.procesar_pdf(contenido, nombre)
        elif tipo == "cobranzas":
            resultado = workflow_automation.procesar_cobranzas(contenido, nombre)
        elif tipo == "generacion_doc":
            resultado = document_processing.procesar_generacion(contenido, nombre)
            tipo = "zip" # To instruct downloading a zip
        elif tipo == "carga_erp":
            resultado = workflow_automation.procesar_carga_erp(contenido, nombre)
        elif tipo == "reporte_rrhh":
            if len(archivos) < 2: raise HTTPException(400, "Se requiere reloj control bruto y plantilla.")
            c1, c2 = contenido, await archivos[1].read()
            resultado = workflow_automation.procesar_rrhh(c1, c2, archivos[0].filename, archivos[1].filename)
        else:
            raise HTTPException(400, f"Tipo no implementado: {tipo}")
    except Exception as e:
        raise HTTPException(400, f"No se pudo procesar el flujo '{tipo}': {str(e)}")

    _limpiar_cache()
    token = uuid.uuid4().hex
    _CACHE[token] = (time.time(), resultado, nombre, tipo)

    analisis_meta = next(a for a in ANALISIS_DISPONIBLES if a["id"] == tipo)

    return JSONResponse(
        content={
            "status": "ok",
            "token": token,
            "tipo": tipo,
        }
    )


@router.get("/api/descargar/excel/{token}")
async def descargar(token: str):
    """Devuelve el Excel del analisis identificado por token."""
    entrada = _CACHE.get(token)
    if not entrada:
        raise HTTPException(404, "Reporte no disponible (expirado o inexistente)")
    _, resultado, nombre_archivo, tipo = entrada
    bytes_excel = reporteService.generar_excel(resultado)

    nombre_base = Path(nombre_archivo).stem
    
    if tipo == "zip":
        nombre_salida = f"reportes_generados_{nombre_base}.zip"
        media = "application/zip"
        bytes_out = resultado["zip_bytes"]
    else:
        nombre_salida = f"resultado_{tipo}_{nombre_base}.xlsx"
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        # Para herramientas que devuelven el dict "resultado" estándar con 'df_dict' vs devolver raw bytes
        if isinstance(resultado, dict) and "excel_bytes" in resultado:
            bytes_out = resultado["excel_bytes"]
        elif isinstance(resultado, dict) and "df_dict" in resultado:
            bytes_out = reporteService.generar_excel(resultado)
        else:
            bytes_out = reporteService.generar_excel({"df_dict": []})

    headers = {"Content-Disposition": f'attachment; filename="{nombre_salida}"'}
    return StreamingResponse(
        iter([bytes_out]),
        headers=headers,
        media_type=media,
    )

@router.get("/api/descargar/pdf/{token}")
async def descargar_pdf(token: str):
    """Devuelve el PDF del analisis identificado por token."""
    entrada = _CACHE.get(token)
    if not entrada:
        raise HTTPException(404, "Reporte no disponible (expirado o inexistente)")
    _, resultado, nombre_archivo, tipo = entrada
    
    if tipo != "inventario":
        raise HTTPException(400, "El reporte PDF solo está disponible para análisis de inventario")

    bytes_pdf = reporteService.generar_pdf_inventario(resultado)

    nombre_base = Path(nombre_archivo).stem
    nombre_salida = f"dashboard_{tipo}_{nombre_base}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{nombre_salida}"'}
    return StreamingResponse(
        iter([bytes_pdf]),
        headers=headers,
        media_type="application/pdf",
    )


@router.get("/dashboard/{token}", response_class=HTMLResponse)
async def ver_dashboard(request: Request, token: str):
    """Muestra el dashboard interactivo del analisis de inventario."""
    entrada = _CACHE.get(token)
    if not entrada:
        raise HTTPException(404, "Reporte no disponible (expirado o inexistente)")
    _, resultado, nombre_archivo, tipo = entrada
    
    if tipo != "inventario":
        raise HTTPException(400, "El dashboard web solo está disponible para análisis de inventario")
        
    return templates.TemplateResponse(
        request,
        "analisis/dashboard.html",
        {
            "resultado": resultado,
            "token": token
        }
    )
