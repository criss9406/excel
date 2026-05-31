"""Tests del analisis de inventario."""
from __future__ import annotations
from io import BytesIO

import pandas as pd
import pytest

from services import inventarioService as inv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _csv_bytes(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def _dataset_basico(fecha_max: str = "2026-04-30") -> pd.DataFrame:
    """Genera un dataset con 4 productos representativos:
       - P_RIESGO    : cobertura insuficiente (stock muy bajo, venta alta).
       - P_SOBRE     : stock altisimo, venta baja -> sobre-stock.
       - P_OK        : equilibrado.
       - P_ZOMBI     : sin ventas en la ventana.
    """
    fechas = pd.date_range(end=fecha_max, periods=30, freq="D")
    filas = []
    # P_RIESGO: stock final 10, venta diaria ~10 -> cobertura 1 dia.
    for f in fechas:
        filas.append({
            "Date": f, "Store ID": "S1", "Product ID": "P_RIESGO",
            "Category": "X", "Region": "N",
            "Inventory Level": 10, "Units Sold": 10, "Units Ordered": 0,
            "Demand Forecast": 10, "Price": 100, "Discount": 0,
            "Weather Condition": "Sunny", "Holiday/Promotion": 0,
            "Competitor Pricing": 100, "Seasonality": "Summer",
        })
    # P_SOBRE: stock 5000, venta diaria 2.
    for f in fechas:
        filas.append({
            "Date": f, "Store ID": "S1", "Product ID": "P_SOBRE",
            "Category": "X", "Region": "N",
            "Inventory Level": 5000, "Units Sold": 2, "Units Ordered": 0,
            "Demand Forecast": 2, "Price": 50, "Discount": 0,
            "Weather Condition": "Sunny", "Holiday/Promotion": 0,
            "Competitor Pricing": 50, "Seasonality": "Summer",
        })
    # P_OK: stock 100, venta diaria 5 -> cobertura 20 dias.
    for f in fechas:
        filas.append({
            "Date": f, "Store ID": "S1", "Product ID": "P_OK",
            "Category": "X", "Region": "N",
            "Inventory Level": 100, "Units Sold": 5, "Units Ordered": 0,
            "Demand Forecast": 5, "Price": 200, "Discount": 0,
            "Weather Condition": "Sunny", "Holiday/Promotion": 0,
            "Competitor Pricing": 200, "Seasonality": "Summer",
        })
    # P_ZOMBI: ultima venta hace >120 dias respecto al fecha_max
    fechas_viejas = pd.date_range(end=pd.Timestamp(fecha_max) - pd.Timedelta(days=200),
                                  periods=20, freq="D")
    for f in fechas_viejas:
        filas.append({
            "Date": f, "Store ID": "S1", "Product ID": "P_ZOMBI",
            "Category": "X", "Region": "N",
            "Inventory Level": 50, "Units Sold": 0, "Units Ordered": 0,
            "Demand Forecast": 0, "Price": 80, "Discount": 0,
            "Weather Condition": "Sunny", "Holiday/Promotion": 0,
            "Competitor Pricing": 80, "Seasonality": "Summer",
        })
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Deteccion de columnas
# ---------------------------------------------------------------------------

def test_detectar_columnas_kaggle():
    df = _dataset_basico().drop(columns=["Discount"])
    mapeo = inv.detectar_columnas(df)
    assert mapeo["fecha"] == "Date"
    assert mapeo["producto"] == "Product ID"
    assert mapeo["stock"] == "Inventory Level"
    assert mapeo["vendidas"] == "Units Sold"
    assert mapeo["precio"] == "Price"


def test_detectar_columnas_espanol():
    df = pd.DataFrame({
        "Fecha": ["2026-01-01"],
        "Producto": ["P1"],
        "Stock": [10],
        "Unidades vendidas": [5],
        "Precio": [100],
    })
    mapeo = inv.detectar_columnas(df)
    assert mapeo["fecha"] == "Fecha"
    assert mapeo["producto"] == "Producto"
    assert mapeo["stock"] == "Stock"
    assert mapeo["vendidas"] == "Unidades vendidas"
    assert mapeo["precio"] == "Precio"


def test_falla_si_faltan_columnas_clave():
    df = pd.DataFrame({"A": [1], "B": [2]})
    with pytest.raises(ValueError, match="Faltan columnas"):
        inv.analizar(_csv_bytes(df), "x.csv")


# ---------------------------------------------------------------------------
# KPI: riesgo de quiebre
# ---------------------------------------------------------------------------

def test_riesgo_quiebre_marca_producto_con_cobertura_baja():
    df = _dataset_basico()
    res = inv.analizar(_csv_bytes(df), "demo.csv", lead_time_dias=7)
    riesgo = res["kpis_inventario"]["riesgo_quiebre"]

    productos = [r["producto"] for r in riesgo["top"]]
    assert "P_RIESGO" in productos
    assert "P_SOBRE" not in productos
    assert "P_OK" not in productos
    assert riesgo["n_productos"] >= 1
    assert riesgo["valor_total_en_riesgo"] > 0


# ---------------------------------------------------------------------------
# KPI: sobre-stock
# ---------------------------------------------------------------------------

def test_sobrestock_marca_producto_con_cobertura_alta():
    df = _dataset_basico()
    res = inv.analizar(_csv_bytes(df), "demo.csv",
                       lead_time_dias=7, factor_sobrestock=4.0)
    sobre = res["kpis_inventario"]["sobre_stock"]

    productos = [r["producto"] for r in sobre["top"]]
    assert "P_SOBRE" in productos
    assert "P_RIESGO" not in productos
    assert sobre["capital_inmovilizado_total"] > 0


# ---------------------------------------------------------------------------
# KPI: ABC
# ---------------------------------------------------------------------------

def test_abc_clasifica_y_suma_100_pct():
    df = _dataset_basico()
    res = inv.analizar(_csv_bytes(df), "demo.csv")
    abc = res["kpis_inventario"]["abc"]

    secciones = abc["secciones"]
    total_pct = sum(s["pct_ingreso"] for s in secciones.values())
    # Tolerar redondeo
    assert 99.5 <= total_pct <= 100.5
    # P_OK tiene precio 200 y 5*30=150 unidades -> mayor ingreso (debe ser clase A)
    ranking = {r["producto"]: r["clase_abc"] for r in abc["ranking_top"]}
    assert ranking.get("P_OK") == "A"


# ---------------------------------------------------------------------------
# KPI: zombis
# ---------------------------------------------------------------------------

def test_zombis_detecta_producto_sin_ventas_recientes():
    df = _dataset_basico()
    res = inv.analizar(_csv_bytes(df), "demo.csv", dias_zombi=60)
    zombis = res["kpis_inventario"]["zombis"]

    productos = [r["producto"] for r in zombis["top"]]
    assert "P_ZOMBI" in productos
    assert "P_RIESGO" not in productos
    assert zombis["valor_inmovilizado_total"] > 0


# ---------------------------------------------------------------------------
# Contrato del resultado
# ---------------------------------------------------------------------------

def test_resultado_tiene_campos_genericos_y_especificos():
    df = _dataset_basico()
    res = inv.analizar(_csv_bytes(df), "demo.csv")

    # Campos genericos que consumen reporte y template
    for clave in ("archivo", "n_filas", "n_columnas", "perfil_columnas",
                  "traza", "resumen", "df_dict", "columnas"):
        assert clave in res, f"falta campo generico: {clave}"

    # Campos especificos
    assert res["tipo_analisis"] == "inventario"
    assert "parametros" in res
    assert "mapeo_columnas" in res
    kpis = res["kpis_inventario"]
    for clave in ("riesgo_quiebre", "sobre_stock", "abc", "zombis"):
        assert clave in kpis

    # Traza no vacia: deteccion + 4 KPIs
    assert len(res["traza"]) >= 5


def test_parametros_quedan_registrados_en_resultado():
    df = _dataset_basico()
    res = inv.analizar(_csv_bytes(df), "demo.csv",
                       lead_time_dias=10, margen_pct=25, dias_zombi=90,
                       factor_sobrestock=5)
    p = res["parametros"]
    assert p["lead_time_dias"] == 10
    assert p["margen_pct"] == 25
    assert p["dias_zombi"] == 90
    assert p["factor_sobrestock"] == 5
