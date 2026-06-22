"""
Servicio de Analisis de Inventario.

Detecta automaticamente las columnas relevantes del dataset (esquema Kaggle u
otros equivalentes en espanol) y calcula cuatro KPIs:

  1. Riesgo de quiebre   — stock insuficiente para cubrir la demanda durante
                           el lead time configurado.
  2. Sobre-stock         — stock que excede varias veces el lead time;
                           capital inmovilizado.
  3. ABC / Pareto        — clasifica productos por aporte al ingreso usando
                           cortes 80 / 15 / 5 del valor acumulado.
  4. Productos zombi     — sin ventas durante un horizonte de dias configurable.

Parametros expuestos en UI:
  - lead_time_dias : horizonte para evaluar quiebre (default 7).
  - margen_pct     : porcentaje de margen sobre Price; deriva el costo unitario
                     usado para estimar capital inmovilizado (default 30).
  - dias_zombi     : ventana sin ventas para considerar producto zombi
                     (default 60).
  - factor_sobrestock : multiplo de lead time a partir del cual hay sobrestock
                        (default 4 — i.e. mas de 4 * lead time de cobertura).

Contrato del dict devuelto: incluye los campos genericos que consumen el
reporte y la plantilla (archivo, n_filas, n_columnas, perfil_columnas, traza,
resumen, df_dict, columnas) y anade:
  - tipo_analisis     : "inventario"
  - parametros        : dict con los parametros usados
  - mapeo_columnas    : dict {canonico: columna_en_archivo}
  - kpis_inventario   : dict con las cuatro secciones de KPIs
"""
from __future__ import annotations
from io import BytesIO
from typing import Any

import pandas as pd

from services.edaService import perfilar_columna
from services.traza import paso


# ---------------------------------------------------------------------------
# Mapeo flexible de columnas
# ---------------------------------------------------------------------------

# Cada entrada: clave canonica -> lista de sinonimos (lower, sin espacios).
# El detector busca por coincidencia exacta normalizada y, si no encuentra,
# por inclusion ("inventory level" contiene "inventory").
_SINONIMOS: dict[str, list[str]] = {
    "fecha":        ["date", "fecha"],
    "tienda":       ["store id", "store", "tienda", "sucursal"],
    "producto":     ["product id", "product", "producto", "sku"],
    "categoria":    ["category", "categoria"],
    "stock":        ["inventory level", "inventario", "stock", "existencias"],
    "vendidas":     ["units sold", "unidades vendidas", "ventas", "vendidas"],
    "precio":       ["price", "precio", "precio unitario"],
}

_REQUERIDAS = ["fecha", "producto", "stock", "vendidas", "precio"]


def _norm(s: str) -> str:
    return "".join(str(s).lower().split())


def detectar_columnas(df: pd.DataFrame) -> dict[str, str]:
    """Devuelve {canonico: columna_real} para las columnas que se encontraron."""
    disponibles = {_norm(c): c for c in df.columns}
    mapeo: dict[str, str] = {}
    for canonico, sinonimos in _SINONIMOS.items():
        # 1) Coincidencia exacta normalizada
        for syn in sinonimos:
            n = _norm(syn)
            if n in disponibles:
                mapeo[canonico] = disponibles[n]
                break
        if canonico in mapeo:
            continue
        # 2) Coincidencia por inclusion (mas permisivo)
        for syn in sinonimos:
            n = _norm(syn)
            for col_norm, col_real in disponibles.items():
                if n in col_norm or col_norm in n:
                    mapeo[canonico] = col_real
                    break
            if canonico in mapeo:
                break
    return mapeo


# ---------------------------------------------------------------------------
# Lectura y Limpieza
# ---------------------------------------------------------------------------

def _limpiar_datos(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    cambios = []
    df_limpio = df.copy()

    # Eliminar duplicados
    dups = df_limpio.duplicated(keep="first")
    if dups.any():
        for idx in df_limpio[dups].index:
            cambios.append({
                "Fila (aprox Excel)": idx + 2,
                "Columna": "(Todas)",
                "Antes": "Fila duplicada",
                "Despues": "Fila eliminada"
            })
        df_limpio = df_limpio[~dups]

    # Rellenar nulos
    for col in df_limpio.columns:
        mask = df_limpio[col].isna()
        if not mask.any():
            continue
            
        if pd.api.types.is_numeric_dtype(df_limpio[col]):
            valor_reemplazo = 0
            desc_reemplazo = "0"
        else:
            valor_reemplazo = "Sin dato"
            desc_reemplazo = "Sin dato"
            
        for idx in df_limpio[mask].index:
            cambios.append({
                "Fila (aprox Excel)": idx + 2,
                "Columna": col,
                "Antes": "Vacio/NaN",
                "Despues": desc_reemplazo
            })
        df_limpio[col] = df_limpio[col].fillna(valor_reemplazo)

    return df_limpio, cambios

def _leer_archivo(contenido: bytes, nombre: str) -> pd.DataFrame:
    nombre_lower = nombre.lower()
    if nombre_lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(BytesIO(contenido), engine="openpyxl")
    if nombre_lower.endswith(".csv"):
        return pd.read_csv(BytesIO(contenido))
    raise ValueError(f"Formato no soportado: {nombre}. Use .xlsx, .xls o .csv")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serie_num(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce")


def _agg_por_producto(df: pd.DataFrame, mapeo: dict[str, str]) -> pd.DataFrame:
    """Resume el dataset a una fila por producto (promedio diario y stock actual).

    - stock_actual: ultimo registro cronologico (si hay fecha) o media reciente.
    - venta_diaria_prom: promedio de unidades vendidas por dia (a nivel producto).
    - precio_prom: precio medio observado.
    - valor_stock: stock_actual * costo_unitario (costo se calcula afuera).
    - ultima_venta: fecha mas reciente con venta > 0 (NaT si nunca vendio).
    """
    col_prod = mapeo["producto"]
    col_stock = mapeo["stock"]
    col_vend = mapeo["vendidas"]
    col_precio = mapeo["precio"]
    col_fecha = mapeo.get("fecha")

    df_local = df.copy()
    df_local[col_stock] = _serie_num(df_local, col_stock)
    df_local[col_vend] = _serie_num(df_local, col_vend)
    df_local[col_precio] = _serie_num(df_local, col_precio)
    if col_fecha:
        df_local[col_fecha] = pd.to_datetime(df_local[col_fecha], errors="coerce")

    # Stock actual: si hay fecha, tomar la mas reciente por producto;
    # si no, tomar la media de stock.
    if col_fecha:
        ordenado = df_local.sort_values(col_fecha)
        stock_actual = ordenado.groupby(col_prod)[col_stock].last()
    else:
        stock_actual = df_local.groupby(col_prod)[col_stock].mean()

    venta_diaria_prom = df_local.groupby(col_prod)[col_vend].mean()
    precio_prom = df_local.groupby(col_prod)[col_precio].mean()
    ingreso_total = (df_local[col_vend] * df_local[col_precio]).groupby(df_local[col_prod]).sum()

    if col_fecha:
        ventas_pos = df_local[df_local[col_vend] > 0]
        ultima_venta = ventas_pos.groupby(col_prod)[col_fecha].max()
    else:
        ultima_venta = pd.Series(pd.NaT, index=stock_actual.index)

    agg = pd.DataFrame({
        "stock_actual": stock_actual,
        "venta_diaria_prom": venta_diaria_prom,
        "precio_prom": precio_prom,
        "ingreso_total": ingreso_total,
        "ultima_venta": ultima_venta,
    })
    agg["producto"] = agg.index
    return agg.reset_index(drop=True)


# ---------------------------------------------------------------------------
# KPI: Riesgo de quiebre
# ---------------------------------------------------------------------------

def _kpi_riesgo_quiebre(
    agg: pd.DataFrame, lead_time_dias: int, costo_unit: pd.Series
) -> tuple[dict, dict]:
    """Producto en riesgo si cobertura (stock / venta_diaria) < lead_time."""
    # Evitar division por cero: si no hay ventas, no hay riesgo definido aqui
    # (eso lo captura el KPI de zombis).
    venta = agg["venta_diaria_prom"].replace(0, pd.NA)
    cobertura_dias = agg["stock_actual"] / venta
    en_riesgo = cobertura_dias < lead_time_dias
    en_riesgo = en_riesgo.fillna(False)

    productos_en_riesgo = agg[en_riesgo].copy()
    productos_en_riesgo["cobertura_dias"] = cobertura_dias[en_riesgo].round(2)
    productos_en_riesgo["dias_faltantes"] = (lead_time_dias - cobertura_dias[en_riesgo]).round(2)
    productos_en_riesgo["valor_riesgo"] = (
        (productos_en_riesgo["venta_diaria_prom"] * lead_time_dias
         - productos_en_riesgo["stock_actual"]).clip(lower=0)
        * productos_en_riesgo["precio_prom"]
    ).round(2)

    productos_en_riesgo = productos_en_riesgo.sort_values("dias_faltantes", ascending=False)

    n = int(en_riesgo.sum())
    valor_total = float(productos_en_riesgo["valor_riesgo"].sum()) if n else 0.0
    top = productos_en_riesgo.head(20)[
        ["producto", "stock_actual", "venta_diaria_prom", "cobertura_dias",
         "dias_faltantes", "valor_riesgo"]
    ].round(2).to_dict(orient="records")

    indices_orig = productos_en_riesgo.index.tolist()
    ejemplos = top[:5]

    paso_traza = paso(
        nombre="Riesgo de quiebre",
        columna=None,
        regla=f"cobertura (stock / venta diaria) >= {lead_time_dias} dias",
        params={"lead_time_dias": lead_time_dias},
        alcance="productos con ventas observadas",
        n_total=int(len(agg)),
        n_alcance=int(agg["venta_diaria_prom"].notna().sum()),
        n_violaciones=n,
        indices=indices_orig,
        ejemplos=ejemplos,
        severidad="info" if n == 0 else "advertencia",
    )

    return {
        "n_productos": n,
        "valor_total_en_riesgo": round(valor_total, 2),
        "top": top,
    }, paso_traza


# ---------------------------------------------------------------------------
# KPI: Sobre-stock
# ---------------------------------------------------------------------------

def _kpi_sobre_stock(
    agg: pd.DataFrame, lead_time_dias: int, factor: float, costo_unit: pd.Series
) -> tuple[dict, dict]:
    """Sobrestock si cobertura > factor * lead_time (capital inmovilizado)."""
    umbral_dias = factor * lead_time_dias
    venta = agg["venta_diaria_prom"].replace(0, pd.NA)
    cobertura_dias = agg["stock_actual"] / venta
    excede = cobertura_dias > umbral_dias
    excede = excede.fillna(False)

    productos = agg[excede].copy()
    productos["cobertura_dias"] = cobertura_dias[excede].round(2)
    productos["dias_excedentes"] = (cobertura_dias[excede] - umbral_dias).round(2)
    productos["capital_inmovilizado"] = (
        (productos["stock_actual"] - umbral_dias * productos["venta_diaria_prom"]).clip(lower=0)
        * costo_unit.loc[productos.index]
    ).round(2)

    productos = productos.sort_values("capital_inmovilizado", ascending=False)

    n = int(excede.sum())
    valor_total = float(productos["capital_inmovilizado"].sum()) if n else 0.0

    top = productos.head(20)[
        ["producto", "stock_actual", "venta_diaria_prom", "cobertura_dias",
         "dias_excedentes", "capital_inmovilizado"]
    ].round(2).to_dict(orient="records")

    paso_traza = paso(
        nombre="Sobre-stock",
        columna=None,
        regla=f"cobertura <= {umbral_dias:.0f} dias (factor {factor} x lead time {lead_time_dias})",
        params={"factor_sobrestock": factor, "lead_time_dias": lead_time_dias},
        alcance="productos con ventas observadas",
        n_total=int(len(agg)),
        n_alcance=int(agg["venta_diaria_prom"].notna().sum()),
        n_violaciones=n,
        indices=productos.index.tolist(),
        ejemplos=top[:5],
        severidad="info" if n == 0 else "advertencia",
    )

    return {
        "n_productos": n,
        "capital_inmovilizado_total": round(valor_total, 2),
        "umbral_dias": round(umbral_dias, 2),
        "top": top,
    }, paso_traza


# ---------------------------------------------------------------------------
# KPI: ABC / Pareto
# ---------------------------------------------------------------------------

def _kpi_abc(agg: pd.DataFrame) -> tuple[dict, dict]:
    """Clasifica productos por aporte al ingreso (80 / 15 / 5)."""
    orden = agg.sort_values("ingreso_total", ascending=False).copy()
    total = float(orden["ingreso_total"].sum())
    if total <= 0:
        # Caso patologico: ingresos cero.
        clases = pd.Series(["C"] * len(orden), index=orden.index)
        orden["clase_abc"] = clases.values
        orden["pct_acumulado"] = 0.0
    else:
        acumulado = orden["ingreso_total"].cumsum() / total
        orden["pct_acumulado"] = (acumulado * 100).round(2)
        orden["clase_abc"] = pd.cut(
            acumulado, bins=[-0.001, 0.80, 0.95, 1.0001], labels=["A", "B", "C"]
        ).astype(str)

    conteo = orden["clase_abc"].value_counts().to_dict()
    valor = orden.groupby("clase_abc", observed=True)["ingreso_total"].sum().round(2).to_dict()

    secciones = {}
    for clase in ("A", "B", "C"):
        secciones[clase] = {
            "n_productos": int(conteo.get(clase, 0)),
            "ingreso": float(valor.get(clase, 0.0)),
            "pct_ingreso": round((valor.get(clase, 0.0) / total) * 100, 2) if total > 0 else 0.0,
        }

    ranking = orden.head(50)[
        ["producto", "ingreso_total", "pct_acumulado", "clase_abc"]
    ].round(2).to_dict(orient="records")

    paso_traza = paso(
        nombre="Clasificacion ABC / Pareto",
        columna=None,
        regla="A: 80% del ingreso acumulado, B: siguiente 15%, C: ultimo 5%",
        params={"cortes_pct": "80 / 95 / 100"},
        alcance="todos los productos con ingreso > 0",
        n_total=int(len(agg)),
        n_alcance=int((orden["ingreso_total"] > 0).sum()),
        n_violaciones=0,
        indices=[],
        ejemplos=ranking[:5],
        severidad="info",
    )

    return {
        "ingreso_total": round(total, 2),
        "secciones": secciones,
        "ranking_top": ranking,
    }, paso_traza


# ---------------------------------------------------------------------------
# KPI: Productos zombi
# ---------------------------------------------------------------------------

def _kpi_zombis(
    agg: pd.DataFrame, dias_zombi: int, fecha_max: pd.Timestamp | None,
    costo_unit: pd.Series,
) -> tuple[dict, dict]:
    if fecha_max is None or pd.isna(fecha_max):
        # No hay columna fecha utilizable: marcamos zombis solo por venta_diaria == 0.
        es_zombi = agg["venta_diaria_prom"].fillna(0) == 0
        dias_sin = pd.Series(pd.NA, index=agg.index, dtype="object")
    else:
        dias_sin = (fecha_max - agg["ultima_venta"]).dt.days
        # Sin ventas registradas o sin ventas en la ventana
        es_zombi = (agg["ultima_venta"].isna()) | (dias_sin > dias_zombi)

    productos = agg[es_zombi].copy()
    productos["dias_sin_venta"] = dias_sin[es_zombi]
    productos["valor_inmovilizado"] = (
        productos["stock_actual"].fillna(0) * costo_unit.loc[productos.index]
    ).round(2)
    # Ordenar primero los mas antiguos (mayor cantidad de dias sin venta) y
    # con mayor capital atrapado.
    productos = productos.sort_values(
        ["valor_inmovilizado", "dias_sin_venta"], ascending=[False, False]
    )

    n = int(es_zombi.sum())
    valor_total = float(productos["valor_inmovilizado"].sum()) if n else 0.0

    top = productos.head(20)[
        ["producto", "stock_actual", "ultima_venta", "dias_sin_venta",
         "valor_inmovilizado"]
    ].copy()
    top["ultima_venta"] = top["ultima_venta"].astype(str).replace("NaT", "—")
    top = top.to_dict(orient="records")

    paso_traza = paso(
        nombre="Productos zombi",
        columna=None,
        regla=(
            f"sin ventas hace mas de {dias_zombi} dias"
            if fecha_max is not None and not pd.isna(fecha_max)
            else "sin columna fecha: zombi = venta diaria promedio igual a 0"
        ),
        params={"dias_zombi": dias_zombi},
        alcance="todos los productos",
        n_total=int(len(agg)),
        n_alcance=int(len(agg)),
        n_violaciones=n,
        indices=productos.index.tolist(),
        ejemplos=top[:5],
        severidad="info" if n == 0 else "advertencia",
    )

    return {
        "n_productos": n,
        "valor_inmovilizado_total": round(valor_total, 2),
        "top": top,
    }, paso_traza


# ---------------------------------------------------------------------------
# KPIs Avanzados
# ---------------------------------------------------------------------------

def _kpi_salud_inventario(
    agg: pd.DataFrame, lead_time_dias: int, factor_sobrestock: float,
    dias_zombi: int, fecha_max: pd.Timestamp | None, costo_unit: pd.Series
) -> dict:
    umbral_dias = factor_sobrestock * lead_time_dias
    venta = agg["venta_diaria_prom"].replace(0, pd.NA)
    cobertura_dias = agg["stock_actual"] / venta
    
    if fecha_max is None or pd.isna(fecha_max):
        es_zombi = agg["venta_diaria_prom"].fillna(0) == 0
    else:
        dias_sin = (fecha_max - agg["ultima_venta"]).dt.days
        es_zombi = (agg["ultima_venta"].isna()) | (dias_sin > dias_zombi)

    es_riesgo = (cobertura_dias < lead_time_dias) & (~es_zombi)
    es_sobre = (cobertura_dias > umbral_dias) & (~es_zombi)
    es_sano = (~es_zombi) & (~es_riesgo) & (~es_sobre)
    
    capital = (agg["stock_actual"].fillna(0) * costo_unit.loc[agg.index]).round(2)
    
    return {
        "zombi": {"n": int(es_zombi.sum()), "capital": float(capital[es_zombi].sum())},
        "sobre_stock": {"n": int(es_sobre.sum()), "capital": float(capital[es_sobre].sum())},
        "riesgo_quiebre": {"n": int(es_riesgo.sum()), "capital": float(capital[es_riesgo].sum())},
        "saludable": {"n": int(es_sano.sum()), "capital": float(capital[es_sano].sum())},
    }

def _kpi_metricas_globales(df: pd.DataFrame, agg: pd.DataFrame, mapeo: dict) -> dict:
    total_vendidas = float(pd.to_numeric(df[mapeo["vendidas"]], errors="coerce").sum())
    total_stock = float(agg["stock_actual"].sum())
    rotacion = total_vendidas / total_stock if total_stock > 0 else 0.0
    
    total_venta_diaria = float(agg["venta_diaria_prom"].sum())
    cobertura_global = total_stock / total_venta_diaria if total_venta_diaria > 0 else 0.0
    
    return {
        "rotacion_unidades": round(rotacion, 2),
        "cobertura_global_dias": round(cobertura_global, 2),
    }

def _kpi_evolucion_historica(df: pd.DataFrame, mapeo: dict) -> list[dict]:
    col_fecha = mapeo.get("fecha")
    if not col_fecha:
        return []
    
    df_temp = df.copy()
    df_temp[col_fecha] = pd.to_datetime(df_temp[col_fecha], errors="coerce")
    df_temp = df_temp.dropna(subset=[col_fecha])
    if df_temp.empty:
        return []
    
    col_vend = mapeo["vendidas"]
    col_stock = mapeo["stock"]
    
    df_temp["mes"] = df_temp[col_fecha].dt.to_period("M").astype(str)
    df_temp[col_vend] = pd.to_numeric(df_temp[col_vend], errors="coerce").fillna(0)
    df_temp[col_stock] = pd.to_numeric(df_temp[col_stock], errors="coerce").fillna(0)

    agg_mensual = df_temp.groupby("mes").agg({
        col_vend: "sum",
        col_stock: "mean"
    }).reset_index()
    
    res = []
    for _, row in agg_mensual.iterrows():
        res.append({
            "fecha": row["mes"],
            "vendidas": round(float(row[col_vend]), 2),
            "stock": round(float(row[col_stock]), 2),
        })
    return res

def _kpi_volatilidad(df: pd.DataFrame, mapeo: dict) -> list[dict]:
    col_fecha = mapeo.get("fecha")
    if not col_fecha:
        return []
        
    col_prod = mapeo["producto"]
    col_vend = mapeo["vendidas"]
    
    df_temp = df.copy()
    df_temp[col_vend] = pd.to_numeric(df_temp[col_vend], errors="coerce").fillna(0)
    df_temp[col_fecha] = pd.to_datetime(df_temp[col_fecha], errors="coerce")
    df_temp = df_temp.dropna(subset=[col_fecha])
    
    if df_temp.empty:
        return []

    volumen = df_temp.groupby(col_prod)[col_vend].sum()
    diario = df_temp.groupby([col_prod, col_fecha])[col_vend].sum().reset_index()
    std = diario.groupby(col_prod)[col_vend].std().fillna(0)
    
    res_df = pd.DataFrame({
        "producto": volumen.index,
        "volumen": volumen.values,
        "volatilidad": std.values
    })
    res_df = res_df.sort_values("volumen", ascending=False).head(50)
    return res_df.to_dict(orient="records")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def analizar(
    contenido: bytes,
    nombre_archivo: str,
    lead_time_dias: int = 7,
    margen_pct: float = 30.0,
    dias_zombi: int = 60,
    factor_sobrestock: float = 4.0,
) -> dict[str, Any]:
    """Punto de entrada del analisis de inventario."""
    df = _leer_archivo(contenido, nombre_archivo)
    df.columns = [str(c).strip() for c in df.columns]

    df, cambios_limpieza = _limpiar_datos(df)

    mapeo = detectar_columnas(df)
    faltantes = [c for c in _REQUERIDAS if c not in mapeo]
    if faltantes:
        # Si faltan columnas clave, devolvemos un resultado con error visible.
        raise ValueError(
            "El archivo no parece un dataset de inventario. Faltan columnas: "
            f"{', '.join(faltantes)}. Esperadas (o sinonimos): "
            "fecha, producto, stock, unidades vendidas, precio."
        )

    perfil_columnas = [perfilar_columna(df[c]) for c in df.columns]

    traza: list[dict] = []
    # Paso introductorio que muestra el mapeo detectado.
    traza.append(paso(
        nombre="Deteccion de columnas",
        columna=None,
        regla="cada rol se asocia a la columna del archivo con nombre equivalente",
        params={k: v for k, v in mapeo.items()},
        alcance="todas las columnas",
        n_total=int(len(df)),
        n_alcance=int(len(df.columns)),
        n_violaciones=0,
        severidad="info",
    ))

    # Agregacion por producto
    agg = _agg_por_producto(df, mapeo)

    # Costo unitario derivado del margen
    factor_costo = max(0.0, 1.0 - margen_pct / 100.0)
    costo_unit = (agg["precio_prom"].fillna(0) * factor_costo)

    # Fecha maxima para zombis
    col_fecha = mapeo.get("fecha")
    if col_fecha:
        fechas = pd.to_datetime(df[col_fecha], errors="coerce")
        fecha_max = fechas.max() if fechas.notna().any() else None
    else:
        fecha_max = None

    riesgo, paso_riesgo = _kpi_riesgo_quiebre(agg, lead_time_dias, costo_unit)
    sobre, paso_sobre = _kpi_sobre_stock(agg, lead_time_dias, factor_sobrestock, costo_unit)
    abc, paso_abc = _kpi_abc(agg)
    zombis, paso_zombi = _kpi_zombis(agg, dias_zombi, fecha_max, costo_unit)
    
    salud_inventario = _kpi_salud_inventario(agg, lead_time_dias, factor_sobrestock, dias_zombi, fecha_max, costo_unit)
    metricas_globales = _kpi_metricas_globales(df, agg, mapeo)
    evolucion_historica = _kpi_evolucion_historica(df, mapeo)
    volatilidad = _kpi_volatilidad(df, mapeo)

    traza.extend([paso_riesgo, paso_sobre, paso_abc, paso_zombi])

    total_viol = sum(p["n_violaciones"] for p in traza)
    por_sev = {"info": 0, "advertencia": 0, "error": 0}
    for p in traza:
        por_sev[p["severidad"]] = por_sev.get(p["severidad"], 0) + 1

    # Serializacion limitada para el reporte / template.
    df_export = df.head(500).astype(object).where(df.head(500).notna(), None)
    df_dict = df_export.to_dict(orient="records")

    return {
        "archivo": nombre_archivo,
        "n_filas": int(len(df)),
        "n_columnas": int(len(df.columns)),
        "perfil_columnas": perfil_columnas,
        "traza": traza,
        "resumen": {
            "total_violaciones": int(total_viol),
            "por_severidad": por_sev,
            "columnas_con_violaciones": 0,
        },
        "df_dict": df_dict,
        "columnas": list(df.columns),
        "tipo_analisis": "inventario",
        "cambios_limpieza": cambios_limpieza,
        "parametros": {
            "lead_time_dias": lead_time_dias,
            "margen_pct": margen_pct,
            "dias_zombi": dias_zombi,
            "factor_sobrestock": factor_sobrestock,
        },
        "mapeo_columnas": mapeo,
        "kpis_inventario": {
            "riesgo_quiebre": riesgo,
            "sobre_stock": sobre,
            "abc": abc,
            "zombis": zombis,
            "salud": salud_inventario,
            "globales": metricas_globales,
            "historico": evolucion_historica,
            "volatilidad": volatilidad,
        },
    }
