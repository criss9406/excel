"""
Checks parametrizables sobre columnas de un DataFrame.

Cada check tiene la firma:
    check(serie: pd.Series, **params) -> tuple[pd.Series, str]

Devuelve:
    - mask_violacion: Serie booleana del mismo indice que la entrada,
      True en las filas que VIOLAN la regla.
    - regla: descripcion textual de la regla aplicada con sus parametros.

Convencion para checks "de columna" (cardinalidad_entre): la mask se llena
de True si la columna entera incumple, o de False si cumple. La regla
contiene la metrica observada.

El runner `aplicar` empaqueta el resultado en un paso de traza, manejando
el filtro `aplica_a` para acotar a un subconjunto de filas.
"""
from __future__ import annotations
import re
from typing import Any, Callable

import numpy as np
import pandas as pd

from services.traza import paso, describir_alcance


# ---------------------------------------------------------------------------
# Checks por fila
# ---------------------------------------------------------------------------

def en_rango(
    serie: pd.Series,
    x_min: float | None = None,
    x_max: float | None = None,
    incluir_min: bool = True,
    incluir_max: bool = True,
) -> tuple[pd.Series, str]:
    """Valores numericos dentro de un rango. Inclusion configurable por extremo."""
    s = pd.to_numeric(serie, errors="coerce")
    mask = pd.Series(False, index=serie.index)

    if x_min is not None:
        mask |= (s < x_min) if incluir_min else (s <= x_min)
    if x_max is not None:
        mask |= (s > x_max) if incluir_max else (s >= x_max)

    # Nulos (no numericos) tambien cuentan como violacion (no caen en el rango)
    mask |= s.isna()

    izq = "[" if incluir_min else "("
    der = "]" if incluir_max else ")"
    lo = "-∞" if x_min is None else str(x_min)
    hi = "+∞" if x_max is None else str(x_max)
    regla = f"valor ∈ {izq}{lo}, {hi}{der}"
    return mask, regla


def no_nulo(serie: pd.Series) -> tuple[pd.Series, str]:
    """Marca filas con valor nulo / NaN / cadena vacia."""
    mask = serie.isna()
    if not pd.api.types.is_numeric_dtype(serie):
        # Detectar strings vacios o solo espacios (compatible pandas 2.x/3.x)
        try:
            txt = serie.astype("string").str.strip()
            mask |= txt.eq("")
        except (TypeError, ValueError):
            pass
    return mask, "valor no nulo y no vacio"


def valor_unico(serie: pd.Series) -> tuple[pd.Series, str]:
    """Marca todas las filas que pertenecen a un grupo duplicado."""
    mask = serie.duplicated(keep=False) & serie.notna()
    return mask, "valor unico en la columna"


def formato_numerico(serie: pd.Series) -> tuple[pd.Series, str]:
    """Marca filas cuyo valor no puede convertirse a numero."""
    convertido = pd.to_numeric(serie, errors="coerce")
    # Falla = no es nulo en origen pero si despues de convertir
    mask = serie.notna() & convertido.isna()
    if serie.dtype == object:
        no_vacio = serie.astype(str).str.strip().ne("")
        mask &= no_vacio
    return mask, "valor convertible a numero"


def formato_fecha(
    serie: pd.Series,
    formato: str | None = None,
    fecha_min: str | None = None,
    fecha_max: str | None = None,
) -> tuple[pd.Series, str]:
    """Marca filas que no parsean a fecha o caen fuera del rango temporal dado."""
    convertido = pd.to_datetime(serie, format=formato, errors="coerce")
    mask = serie.notna() & convertido.isna()

    if fecha_min is not None:
        fm = pd.to_datetime(fecha_min)
        mask |= (convertido < fm)
    if fecha_max is not None:
        fM = pd.to_datetime(fecha_max)
        mask |= (convertido > fM)

    partes = []
    if formato:
        partes.append(f"formato={formato}")
    if fecha_min:
        partes.append(f"≥ {fecha_min}")
    if fecha_max:
        partes.append(f"≤ {fecha_max}")
    suf = f" ({', '.join(partes)})" if partes else ""
    return mask, f"fecha valida{suf}"


def formato_texto(serie: pd.Series, patron: str) -> tuple[pd.Series, str]:
    """Marca filas cuyo texto no calza con el patron regex dado."""
    compilado = re.compile(patron)
    def calza(v):
        if pd.isna(v):
            return False
        return bool(compilado.fullmatch(str(v)))
    mask = ~serie.apply(calza)
    return mask, f"texto calza patron /{patron}/"


def categorias_permitidas(
    serie: pd.Series, valores: list[Any]
) -> tuple[pd.Series, str]:
    """Marca filas cuyo valor no esta en la lista de categorias permitidas."""
    mask = ~serie.isin(valores)
    permitido = ", ".join(map(str, valores))
    return mask, f"valor ∈ {{{permitido}}}"


def outliers_iqr(serie: pd.Series, k: float = 1.5) -> tuple[pd.Series, str]:
    """Outliers por regla IQR: fuera de [Q1 - k*IQR, Q3 + k*IQR]."""
    s = pd.to_numeric(serie, errors="coerce")
    q1 = s.quantile(0.25)
    q3 = s.quantile(0.75)
    iqr = q3 - q1
    lo = q1 - k * iqr
    hi = q3 + k * iqr
    mask = (s < lo) | (s > hi)
    mask = mask.fillna(False)
    regla = f"valor ∈ [{lo:.2f}, {hi:.2f}] (IQR k={k}, Q1={q1:.2f}, Q3={q3:.2f})"
    return mask, regla


def outliers_zscore(serie: pd.Series, umbral: float = 3.0) -> tuple[pd.Series, str]:
    """Outliers por z-score: |z| > umbral."""
    s = pd.to_numeric(serie, errors="coerce")
    media = s.mean()
    desv = s.std(ddof=0)
    if desv == 0 or pd.isna(desv):
        mask = pd.Series(False, index=serie.index)
        return mask, f"|z| ≤ {umbral} (desviacion=0, no aplicable)"
    z = (s - media) / desv
    mask = (z.abs() > umbral).fillna(False)
    return mask, f"|z| ≤ {umbral} (media={media:.2f}, desv={desv:.2f})"


# ---------------------------------------------------------------------------
# Check de columna (nivel agregado, no por fila)
# ---------------------------------------------------------------------------

def cardinalidad_entre(
    serie: pd.Series, min_: int | None = None, max_: int | None = None
) -> tuple[pd.Series, str]:
    """Valida que la cantidad de valores unicos este en el rango [min_, max_].
    Si incumple, marca toda la columna como violacion."""
    n_unicos = serie.nunique(dropna=True)
    incumple = False
    if min_ is not None and n_unicos < min_:
        incumple = True
    if max_ is not None and n_unicos > max_:
        incumple = True

    mask = pd.Series(incumple, index=serie.index)
    lo = "-∞" if min_ is None else str(min_)
    hi = "+∞" if max_ is None else str(max_)
    regla = f"cardinalidad ∈ [{lo}, {hi}] (observada: {n_unicos})"
    return mask, regla


# ---------------------------------------------------------------------------
# Runner: aplica un check a un DataFrame y devuelve un paso de traza
# ---------------------------------------------------------------------------

def _construir_mask_alcance(df: pd.DataFrame, aplica_a) -> pd.Series:
    """Convierte aplica_a (dict | callable | None) en mask booleana."""
    if aplica_a is None:
        return pd.Series(True, index=df.index)
    if callable(aplica_a):
        return aplica_a(df).astype(bool)
    if isinstance(aplica_a, dict):
        mask = pd.Series(True, index=df.index)
        for col, val in aplica_a.items():
            if col not in df.columns:
                return pd.Series(False, index=df.index)
            if isinstance(val, (list, tuple, set)):
                mask &= df[col].isin(list(val))
            else:
                mask &= df[col] == val
        return mask
    raise TypeError(f"aplica_a debe ser dict, callable o None — recibido {type(aplica_a)}")


def aplicar(
    df: pd.DataFrame,
    columna: str,
    check_fn: Callable,
    params: dict[str, Any] | None = None,
    aplica_a: dict | Callable | None = None,
    etiqueta: str | None = None,
    max_ejemplos: int = 5,
) -> dict[str, Any]:
    """Corre un check sobre `columna` del df, opcionalmente filtrado por aplica_a,
    y devuelve un paso de traza en el formato canonico."""
    params = params or {}
    n_total = len(df)
    nombre = etiqueta or check_fn.__name__
    alcance_txt = describir_alcance(aplica_a if isinstance(aplica_a, dict) else None)
    if callable(aplica_a) and not isinstance(aplica_a, dict):
        alcance_txt = f"filtro callable: {getattr(aplica_a, '__doc__', '') or aplica_a.__name__}"

    if columna not in df.columns:
        return paso(
            nombre=nombre,
            columna=columna,
            regla=f"columna '{columna}' no existe en el archivo",
            params=params,
            alcance=alcance_txt,
            n_total=n_total,
            n_alcance=0,
            n_violaciones=0,
            severidad="error",
        )

    mask_scope = _construir_mask_alcance(df, aplica_a)
    df_scope = df[mask_scope]
    n_alcance = len(df_scope)

    if n_alcance == 0:
        return paso(
            nombre=nombre,
            columna=columna,
            regla=f"sin filas en alcance — check no aplicado",
            params=params,
            alcance=alcance_txt,
            n_total=n_total,
            n_alcance=0,
            n_violaciones=0,
            severidad="info",
        )

    mask_viol, regla = check_fn(df_scope[columna], **params)
    indices = df_scope.index[mask_viol].tolist()

    ejemplos_df = df.loc[indices].head(max_ejemplos)
    ejemplos = ejemplos_df.astype(object).where(ejemplos_df.notna(), None).to_dict(orient="records")

    severidad = "info" if not indices else "advertencia"

    return paso(
        nombre=nombre,
        columna=columna,
        regla=regla,
        params=params,
        alcance=alcance_txt,
        n_total=n_total,
        n_alcance=n_alcance,
        n_violaciones=len(indices),
        indices=indices,
        ejemplos=ejemplos,
        severidad=severidad,
    )
