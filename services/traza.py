"""
Formato estandar de traza para los analisis.

Cada paso describe: que regla se aplico, sobre que columna y subset de filas,
con que parametros, cuantas violaciones encontro y ejemplos concretos.

La traza es lo que se muestra al usuario como "no es magia" — el detalle
del proceso paso a paso.
"""
from __future__ import annotations
from typing import Any


SEVERIDADES = ("info", "advertencia", "error")


def paso(
    nombre: str,
    columna: str | None = None,
    regla: str = "",
    params: dict[str, Any] | None = None,
    alcance: str = "todas las filas",
    n_total: int = 0,
    n_alcance: int = 0,
    n_violaciones: int = 0,
    indices: list[int] | None = None,
    ejemplos: list[dict[str, Any]] | None = None,
    severidad: str = "info",
) -> dict[str, Any]:
    """Construye un paso de traza con el formato canonico."""
    if severidad not in SEVERIDADES:
        raise ValueError(f"severidad invalida: {severidad}. Validas: {SEVERIDADES}")
    return {
        "nombre": nombre,
        "columna": columna,
        "regla": regla,
        "params": params or {},
        "alcance": alcance,
        "n_total": n_total,
        "n_alcance": n_alcance,
        "n_violaciones": n_violaciones,
        "indices": indices or [],
        "ejemplos": ejemplos or [],
        "severidad": severidad,
    }


def describir_alcance(aplica_a: dict[str, Any] | None) -> str:
    """Convierte un dict de filtros AND en texto legible para la traza."""
    if not aplica_a:
        return "todas las filas"
    partes = []
    for col, val in aplica_a.items():
        if isinstance(val, (list, tuple, set)):
            partes.append(f"{col} ∈ {{{', '.join(map(str, val))}}}")
        else:
            partes.append(f"{col} = {val}")
    return "filas donde " + " y ".join(partes)
