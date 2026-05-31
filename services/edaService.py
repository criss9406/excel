"""
Servicio de EDA generico.

Lee un archivo tabular (Excel o CSV), perfila cada columna, infiere su tipo
y aplica los checks correspondientes. Devuelve:

    {
        "archivo": str,
        "n_filas": int,
        "n_columnas": int,
        "perfil_columnas": [ {columna, tipo_inferido, n_nulos, n_unicos, ejemplos}, ... ],
        "traza": [ <pasos de checks ejecutados> ],
        "resumen": {
            "total_violaciones": int,
            "por_severidad": {info, advertencia, error},
            "columnas_con_violaciones": int,
        },
        "df_dict": [ {col: val, ...}, ... ]  # filas originales serializadas, para reporte
    }
"""
from __future__ import annotations
from io import BytesIO
from typing import Any

import pandas as pd

from services import checks as ck


# Umbral para considerar que una columna "object" en realidad es numerica/fecha
UMBRAL_CONVERSION = 0.9


def leer_archivo(contenido: bytes, nombre: str) -> pd.DataFrame:
    """Lee bytes de un archivo .xlsx o .csv y devuelve un DataFrame."""
    nombre_lower = nombre.lower()
    if nombre_lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(BytesIO(contenido), engine="openpyxl")
    if nombre_lower.endswith(".csv"):
        return pd.read_csv(BytesIO(contenido))
    raise ValueError(f"Formato no soportado: {nombre}. Use .xlsx, .xls o .csv")


def _intentar_conversion(serie: pd.Series, conversor) -> float:
    """Devuelve la proporcion de valores no nulos que se convierten exitosamente."""
    no_nulos = serie.dropna()
    if len(no_nulos) == 0:
        return 0.0
    convertido = conversor(no_nulos)
    return convertido.notna().sum() / len(no_nulos)


def inferir_tipo(serie: pd.Series) -> str:
    """Devuelve uno de: 'numerico', 'fecha', 'booleano', 'categorico', 'texto'."""
    if pd.api.types.is_bool_dtype(serie):
        return "booleano"
    if pd.api.types.is_numeric_dtype(serie):
        return "numerico"
    if pd.api.types.is_datetime64_any_dtype(serie):
        return "fecha"

    # Para object/string: intentar convertir
    if _intentar_conversion(serie, lambda s: pd.to_numeric(s, errors="coerce")) >= UMBRAL_CONVERSION:
        return "numerico"
    if _intentar_conversion(serie, lambda s: pd.to_datetime(s, errors="coerce")) >= UMBRAL_CONVERSION:
        return "fecha"

    # Categorico si tiene pocos valores unicos relativos
    n = len(serie.dropna())
    n_unicos = serie.nunique(dropna=True)
    if n > 0 and n_unicos > 0 and (n_unicos / n) <= 0.1 and n_unicos <= 20:
        return "categorico"

    return "texto"


def perfilar_columna(serie: pd.Series) -> dict[str, Any]:
    """Genera un perfil descriptivo de una columna."""
    tipo = inferir_tipo(serie)
    no_nulos = serie.dropna()
    perfil: dict[str, Any] = {
        "columna": str(serie.name),
        "tipo_inferido": tipo,
        "n_total": int(len(serie)),
        "n_nulos": int(serie.isna().sum()),
        "n_unicos": int(serie.nunique(dropna=True)),
        "ejemplos": [str(v) for v in no_nulos.head(3).tolist()],
    }
    if tipo == "numerico":
        s = pd.to_numeric(serie, errors="coerce")
        perfil["min"] = float(s.min()) if s.notna().any() else None
        perfil["max"] = float(s.max()) if s.notna().any() else None
        perfil["media"] = float(s.mean()) if s.notna().any() else None
    return perfil


def _checks_por_tipo(df: pd.DataFrame, columna: str, tipo: str) -> list[dict]:
    """Lista los pasos de traza para una columna segun su tipo inferido."""
    pasos = []
    # Universal: nulos
    pasos.append(ck.aplicar(df, columna, ck.no_nulo, etiqueta=f"{columna}: sin nulos"))

    if tipo == "numerico":
        pasos.append(ck.aplicar(
            df, columna, ck.formato_numerico,
            etiqueta=f"{columna}: valores convertibles a numero",
        ))
        pasos.append(ck.aplicar(
            df, columna, ck.outliers_iqr, params={"k": 1.5},
            etiqueta=f"{columna}: sin outliers (IQR)",
        ))
    elif tipo == "fecha":
        pasos.append(ck.aplicar(
            df, columna, ck.formato_fecha,
            etiqueta=f"{columna}: fechas validas",
        ))
    elif tipo == "categorico":
        # Cardinalidad razonable: entre 2 y 20 categorias
        pasos.append(ck.aplicar(
            df, columna, ck.cardinalidad_entre, params={"min_": 2, "max_": 20},
            etiqueta=f"{columna}: cardinalidad esperada",
        ))
    # texto, booleano: solo no_nulo
    return pasos


def detectar_duplicados_fila(df: pd.DataFrame) -> dict[str, Any]:
    """Paso de traza que reporta filas completamente duplicadas."""
    from services.traza import paso
    mask = df.duplicated(keep=False)
    indices = df.index[mask].tolist()
    ejemplos_df = df.loc[indices].head(5)
    ejemplos = ejemplos_df.astype(object).where(ejemplos_df.notna(), None).to_dict(orient="records")
    severidad = "info" if not indices else "advertencia"
    return paso(
        nombre="Filas duplicadas completas",
        columna=None,
        regla="cada fila es unica considerando todas sus columnas",
        params={},
        alcance="todas las filas",
        n_total=len(df),
        n_alcance=len(df),
        n_violaciones=len(indices),
        indices=indices,
        ejemplos=ejemplos,
        severidad=severidad,
    )


def analizar(contenido: bytes, nombre_archivo: str) -> dict[str, Any]:
    """Punto de entrada principal del EDA generico."""
    df = leer_archivo(contenido, nombre_archivo)
    df.columns = [str(c).strip() for c in df.columns]

    perfil_columnas = [perfilar_columna(df[c]) for c in df.columns]
    tipos = {p["columna"]: p["tipo_inferido"] for p in perfil_columnas}

    traza: list[dict] = []
    traza.append(detectar_duplicados_fila(df))

    for columna in df.columns:
        traza.extend(_checks_por_tipo(df, columna, tipos[columna]))

    total_viol = sum(p["n_violaciones"] for p in traza)
    por_sev = {"info": 0, "advertencia": 0, "error": 0}
    cols_con_viol: set[str] = set()
    for p in traza:
        por_sev[p["severidad"]] = por_sev.get(p["severidad"], 0) + 1
        if p["n_violaciones"] > 0 and p["columna"]:
            cols_con_viol.add(p["columna"])

    # Serializacion del df para reporte/template (limitada a primeras 500 filas)
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
            "columnas_con_violaciones": len(cols_con_viol),
        },
        "df_dict": df_dict,
        "columnas": list(df.columns),
    }
