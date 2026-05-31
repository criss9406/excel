"""Tests unitarios sobre cada check + el runner aplicar()."""
import pandas as pd
import pytest

from services import checks as ck
from services.traza import describir_alcance


# ---------------------------------------------------------------------------
# en_rango
# ---------------------------------------------------------------------------

def test_en_rango_basico():
    s = pd.Series([0, 5, 10, 15, -1, None])
    mask, regla = ck.en_rango(s, x_min=0, x_max=10)
    # 0 y 10 dentro (inclusivo), 15 fuera por arriba, -1 fuera por abajo, None viola
    assert mask.tolist() == [False, False, False, True, True, True]
    assert "[0" in regla and "10]" in regla


def test_en_rango_extremos_excluidos():
    s = pd.Series([0, 5, 10])
    mask, regla = ck.en_rango(s, x_min=0, x_max=10, incluir_min=False, incluir_max=False)
    assert mask.tolist() == [True, False, True]
    assert "(0" in regla and "10)" in regla


def test_en_rango_solo_minimo():
    s = pd.Series([-1, 0, 100])
    mask, _ = ck.en_rango(s, x_min=0)
    assert mask.tolist() == [True, False, False]


# ---------------------------------------------------------------------------
# no_nulo
# ---------------------------------------------------------------------------

def test_no_nulo_detecta_nulos_y_vacios():
    s = pd.Series(["a", "", " ", None, "b"])
    mask, _ = ck.no_nulo(s)
    assert mask.tolist() == [False, True, True, True, False]


# ---------------------------------------------------------------------------
# valor_unico
# ---------------------------------------------------------------------------

def test_valor_unico_marca_todos_los_duplicados():
    s = pd.Series(["A", "B", "A", "C", "B"])
    mask, _ = ck.valor_unico(s)
    # A y B aparecen dos veces; ambas instancias marcadas
    assert mask.tolist() == [True, True, True, False, True]


# ---------------------------------------------------------------------------
# formato_numerico
# ---------------------------------------------------------------------------

def test_formato_numerico_detecta_no_numericos():
    s = pd.Series(["10", "abc", "3.14", "", None, "1,5"])
    mask, _ = ck.formato_numerico(s)
    # "abc" no es numero; "1,5" tampoco (coma decimal no parsea por defecto)
    assert mask[1] == True
    assert mask[5] == True
    assert mask[0] == False
    assert mask[2] == False


# ---------------------------------------------------------------------------
# formato_fecha
# ---------------------------------------------------------------------------

def test_formato_fecha_invalidas():
    s = pd.Series(["2024-01-01", "no-es-fecha", "2024-12-31"])
    mask, _ = ck.formato_fecha(s, formato="%Y-%m-%d")
    assert mask.tolist() == [False, True, False]


def test_formato_fecha_rango_temporal():
    s = pd.Series(["2024-01-01", "2025-06-15", "2026-01-01"])
    mask, _ = ck.formato_fecha(s, formato="%Y-%m-%d", fecha_min="2025-01-01", fecha_max="2025-12-31")
    assert mask.tolist() == [True, False, True]


# ---------------------------------------------------------------------------
# formato_texto
# ---------------------------------------------------------------------------

def test_formato_texto_regex():
    s = pd.Series(["SKU-001", "SKU-002", "ABC", "SKU-999", None])
    mask, _ = ck.formato_texto(s, patron=r"SKU-\d{3}")
    assert mask.tolist() == [False, False, True, False, True]


# ---------------------------------------------------------------------------
# categorias_permitidas
# ---------------------------------------------------------------------------

def test_categorias_permitidas():
    s = pd.Series(["activo", "inactivo", "pendiente", "activo"])
    mask, _ = ck.categorias_permitidas(s, valores=["activo", "inactivo"])
    assert mask.tolist() == [False, False, True, False]


# ---------------------------------------------------------------------------
# outliers_iqr
# ---------------------------------------------------------------------------

def test_outliers_iqr_extremos():
    s = pd.Series([10, 11, 12, 13, 14, 15, 1000])
    mask, regla = ck.outliers_iqr(s, k=1.5)
    assert mask.iloc[-1] == True
    assert mask.iloc[:-1].sum() == 0
    assert "IQR" in regla


# ---------------------------------------------------------------------------
# outliers_zscore
# ---------------------------------------------------------------------------

def test_outliers_zscore():
    s = pd.Series([10, 10, 10, 10, 10, 10, 100])
    mask, _ = ck.outliers_zscore(s, umbral=2.0)
    assert mask.iloc[-1] == True


def test_outliers_zscore_sin_desviacion():
    s = pd.Series([5, 5, 5, 5])
    mask, regla = ck.outliers_zscore(s, umbral=3)
    assert mask.sum() == 0
    assert "no aplicable" in regla


# ---------------------------------------------------------------------------
# cardinalidad_entre
# ---------------------------------------------------------------------------

def test_cardinalidad_entre_cumple():
    s = pd.Series(["a", "b", "c"])
    mask, regla = ck.cardinalidad_entre(s, min_=2, max_=5)
    assert mask.sum() == 0
    assert "observada: 3" in regla


def test_cardinalidad_entre_incumple():
    s = pd.Series(["a", "a", "a"])
    mask, regla = ck.cardinalidad_entre(s, min_=2, max_=5)
    # Cardinalidad = 1 < 2 → toda la columna marcada
    assert mask.all()
    assert "observada: 1" in regla


# ---------------------------------------------------------------------------
# Runner: aplicar()
# ---------------------------------------------------------------------------

def test_aplicar_sin_filtro():
    df = pd.DataFrame({"stock": [10, -5, 0, 50, -1]})
    p = ck.aplicar(df, "stock", ck.en_rango, params={"x_min": 0})
    assert p["n_total"] == 5
    assert p["n_alcance"] == 5
    assert p["n_violaciones"] == 2
    assert p["severidad"] == "advertencia"
    assert p["alcance"] == "todas las filas"


def test_aplicar_con_filtro_dict():
    df = pd.DataFrame({
        "estado": ["activo", "activo", "inactivo", "activo"],
        "stock": [10, -5, -100, 50],
    })
    p = ck.aplicar(df, "stock", ck.en_rango, params={"x_min": 0}, aplica_a={"estado": "activo"})
    # solo evalua los 3 activos; -5 viola; -100 no entra al alcance
    assert p["n_alcance"] == 3
    assert p["n_violaciones"] == 1
    assert "estado = activo" in p["alcance"]


def test_aplicar_con_filtro_lista():
    df = pd.DataFrame({
        "estado": ["activo", "promo", "inactivo", "promo"],
        "stock": [-1, -2, -3, 10],
    })
    p = ck.aplicar(df, "stock", ck.en_rango, params={"x_min": 0}, aplica_a={"estado": ["activo", "promo"]})
    assert p["n_alcance"] == 3
    assert p["n_violaciones"] == 2


def test_aplicar_con_filtro_callable():
    df = pd.DataFrame({"precio": [10, 20, 5], "costo": [12, 15, 4]})
    p = ck.aplicar(
        df, "precio", ck.en_rango,
        params={"x_min": 0},
        aplica_a=lambda d: d["precio"] > d["costo"],
    )
    # 2 filas pasan el filtro callable (precio>costo: idx 1 y 2), ninguna viola x_min=0
    assert p["n_alcance"] == 2
    assert p["n_violaciones"] == 0


def test_aplicar_columna_inexistente():
    df = pd.DataFrame({"a": [1, 2]})
    p = ck.aplicar(df, "no_existe", ck.en_rango, params={"x_min": 0})
    assert p["severidad"] == "error"
    assert "no existe" in p["regla"]


def test_aplicar_genera_ejemplos():
    df = pd.DataFrame({"sku": ["A", "B", "A", "C", "B", "A"]})
    p = ck.aplicar(df, "sku", ck.valor_unico)
    assert p["n_violaciones"] == 5  # A,B,A,B,A todos duplicados
    assert len(p["ejemplos"]) == 5


# ---------------------------------------------------------------------------
# describir_alcance
# ---------------------------------------------------------------------------

def test_describir_alcance_none():
    assert describir_alcance(None) == "todas las filas"


def test_describir_alcance_dict_simple():
    assert describir_alcance({"estado": "activo"}) == "filas donde estado = activo"


def test_describir_alcance_dict_lista():
    txt = describir_alcance({"estado": ["activo", "promo"]})
    assert "estado ∈" in txt
    assert "activo" in txt and "promo" in txt
