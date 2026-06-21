# Plataforma de Demos de Backoffice

> **Nombre de la carpeta:** se conserva `conciliacion_bancaria/` por historia. El producto actual es un **portafolio de demos** que muestra las ventajas de usar código en procesos de backoffice. Renombrar queda pendiente.

---

## 1. Visión

Plataforma web donde el usuario sube un archivo, elige un tipo de análisis desde un menú desplegable y obtiene:

1. Un **análisis en pantalla** con métricas, hallazgos y el **proceso paso a paso** ("no es magia": cada regla aplicada, sus parámetros y los registros violatorios).
2. Un **reporte descargable** (Excel y/o PDF) con el desglose completo.

La idea es que cada análisis del menú demuestre una capacidad distinta de automatización en backoffice, manteniendo el motor de checks parametrizable y reutilizable entre análisis.

---

## 2. Estado actual — Fase 2 cerrada

### Lo que existe
- Esqueleto FastAPI siguiendo `ABOUT ME/ARQUITECTURA.md`: `main.py`, `routes/`, `services/`, `templates/`, `static/`.
- Motor de **checks parametrizables** (`services/checks.py`): 10 helpers con soporte de filtro `aplica_a` (dict, callable o `None`).
- **Traza estándar** (`services/traza.py`): cada paso registra regla, parámetros, alcance, filas evaluadas, violaciones y ejemplos.
- **Análisis #1 — EDA genérico** (`services/edaService.py`): autodetecta tipos (numérico, fecha, categórico, texto, booleano) y aplica los checks correspondientes.
- **Análisis #2 — Inventario** (`services/inventarioService.py`):
  - Detecta automáticamente las columnas relevantes (mapeo flexible con sinónimos ES/EN: `fecha`, `producto`, `stock`, `vendidas`, `precio`).
  - KPIs: riesgo de quiebre (cobertura < lead time), sobre-stock (cobertura > factor × lead time), ABC/Pareto (80/15/5 sobre ingreso) y productos zombi (sin ventas en una ventana).
  - Parámetros de UI: `lead_time_dias` (default 7), `margen_pct` (30), `dias_zombi` (60), `factor_sobrestock` (4 × lead time).
  - Costo unitario derivado de `Price × (1 − margen)` para estimar capital inmovilizado.
- **Reporte Excel** (`services/reporteService.py`): 5 hojas para EDA (Resumen, Perfil columnas, Pasos del proceso, Hallazgos, Datos marcados); 8 hojas para Inventario (Resumen, Parámetros, Riesgo de quiebre, Sobre-stock, ABC, Productos zombi, Pasos del proceso, Datos). Encabezados destacados, freeze panes, anchos automáticos y auto-filtro en todas.
- **UI** (`templates/analisis/index.html` + `resultado.html`): dropdown de tipo de análisis con inputs condicionales (solo aparecen los parámetros de inventario cuando se elige esa opción); página de resultado adaptada por tipo (KPIs específicos de inventario o perfil + hallazgos para EDA) y timeline colapsable del proceso.
- **Tests unitarios**: 33/33 verdes (24 sobre checks + 9 sobre inventario).
- **Datasets demo** (`data/`):
  - `retail_store_inventory.csv` (Kaggle · 73.100 filas · 15 columnas)
  - `retail_store_inventory_sucio.csv` (3.015 filas con problemas inyectados de forma controlada para mostrar el detector)

### Cambios introducidos por Fase 2 (referencia técnica)

Archivos tocados dentro de `conciliacion_bancaria/`:

- **`services/inventarioService.py`** (nuevo) — mapeo flexible ES/EN de columnas (`fecha`, `producto`, `stock`, `vendidas`, `precio`, además de `tienda` y `categoría` opcionales) + cuatro KPIs (riesgo de quiebre, sobre-stock, ABC/Pareto 80/15/5, productos zombi) con traza estándar reutilizando `services/traza.py`.
- **`services/reporteService.py`** — `generar_excel` bifurca por `tipo_analisis`: 8 hojas para inventario (Resumen, Parámetros, Riesgo de quiebre, Sobre-stock, ABC, Productos zombi, Pasos del proceso, Datos). Se corrigió además un bug preexistente en `_estilizar_hoja` que rompía con NaN en columnas string del dataset sucio (`fillna("")` antes de `astype(str)`).
- **`routes/analisisRoutes.py`** — entrada `inventario` en `ANALISIS_DISPONIBLES`, rama del POST `/analizar` con parámetros `Form` (`lead_time_dias`, `margen_pct`, `dias_zombi`, `factor_sobrestock`), cache extendido a 4-tupla incluyendo `tipo`, nombre del archivo descargado generalizado (`reporte_{tipo}_{base}.xlsx`), nuevo filtro Jinja `fmt_moneda`.
- **`templates/analisis/index.html`** — `<fieldset>` con los inputs de los cuatro parámetros del análisis; toggle JS que los muestra solo cuando se elige inventario en el dropdown.
- **`templates/analisis/resultado.html`** — render condicional según `resultado.tipo_analisis`: bloques de KPIs específicos de inventario con tablas top (riesgo, sobre-stock, ABC con ranking top 50, zombis) cuando aplica; el flujo EDA queda intacto.
- **`static/css/styles.css`** — estilos para `form-fieldset`, `form-grid`, grid ABC, badges A/B/C, `param-list`, y soporte para `input[type="number"]`.
- **`tests/test_inventario.py`** (nuevo) — 9 tests: detección de columnas (Kaggle y español), error si faltan columnas, validación de los cuatro KPIs sobre un dataset sintético con productos representativos (`P_RIESGO`, `P_SOBRE`, `P_OK`, `P_ZOMBI`), y contrato del dict resultado.

Parámetros expuestos en UI con sus defaults: `lead_time_dias=7`, `margen_pct=30`, `dias_zombi=60`, `factor_sobrestock=4` (× lead time). El costo unitario se deriva de `Price × (1 − margen)` y se usa para estimar capital inmovilizado en sobre-stock y zombis.

### Lo que ya no aplica (versión anterior)
- El antiguo MVP era un script único (`main.py`, ~540 líneas) que cruzaba cartolas Santander contra registros internos de tienda. Ese archivo **sigue en la carpeta** pero **no está conectado a la app** y **no aparece en el dropdown público**: queda como código legacy/privado.
- La visión previa era una "plataforma genérica de procesamiento Excel". La actual es un **portafolio de demos comerciables** con motor compartido.

---

## 3. Plan acordado

Cada fase añade un análisis al dropdown manteniendo el mismo motor.

| Fase | Análisis | Estado |
|------|----------|--------|
| 1 | **EDA genérico** — autodetecta tipos y corre checks (nulos, formatos, outliers, duplicados, cardinalidad) | ✅ Cerrada |
| 2 | **Inventario** — riesgo de quiebre, sobre-stock, ABC/Pareto, productos zombi | ✅ Cerrada |
| 3 | **Conciliación bancaria** — refactor del legacy a la arquitectura nueva | 🚫 No público (queda en repo) |
| 4 | **Consolidación por zona** — unión multi-archivo y agrupación geográfica/tienda | 🔜 Siguiente |

### Decisiones cerradas
- **Sin DB**: cada análisis es one-shot, datos en memoria con TTL (1h). Reportes generan al vuelo.
- **Schema de Inventario adaptado al dataset real**: en vez de las 7 columnas que se planearon inicialmente, se usan las 15 columnas de Kaggle. Se derivan costo (margen %) y lead time como parámetros de UI.
- **Traza visible desde el día 1** (formato `{paso, regla, params, alcance, violaciones, ejemplos}`).
- **Presentación amigable end-to-end** — la calidad visual no termina en la UI: los archivos generados (Excel, PDF, etc.) deben llegar al usuario listos para leer, sin que tenga que ajustar anchos, congelar filas ni descifrar encabezados estilo `snake_case`. Encabezados destacados, freeze panes, anchos automáticos, auto-filtros y nombres en español son piso mínimo. Un reporte "tosco" rompe la percepción de producto aunque la lógica detrás sea correcta.
- **Local primero, deploy a Railway al cerrar Fase 2** — listo para empaquetar.

---

## 4. Stack

Alineado con `ABOUT ME/ARQUITECTURA.md`, salvo que:
- **pandas** se agrega como dependencia core (no estaba en la plantilla por defecto).
- **No hay BD** todavía — entra cuando un análisis necesite histórico.

Resumen: Python 3.14 · FastAPI · Jinja2 SSR · pandas · openpyxl · reportlab · pytest · Uvicorn local · Railway al deploy.

---

## 5. Estructura

```
conciliacion_bancaria/
├── main.py                       # Entry FastAPI
├── routes/analisisRoutes.py      # GET / · POST /analizar · GET /descargar/{token}
├── services/
│   ├── traza.py                  # Formato canónico de paso
│   ├── checks.py                 # 10 helpers + runner aplicar()
│   ├── edaService.py             # Análisis #1
│   ├── inventarioService.py      # Análisis #2 (mapeo flexible + 4 KPIs)
│   └── reporteService.py         # Excel adaptativo (5 hojas EDA / 8 hojas Inventario)
├── templates/
│   ├── base.html
│   └── analisis/{index,resultado}.html
├── static/css/styles.css
├── tests/
│   ├── test_checks.py            # 24 tests
│   └── test_inventario.py        # 9 tests
├── data/
│   ├── retail_store_inventory.csv          # Dataset real Kaggle
│   ├── retail_store_inventory_sucio.csv    # Versión con problemas inyectados
│   ├── ejemplo_tienda.xlsx                 # Demo legacy
│   └── Cartola de cuenta Corriente - Abril 2026.xlsx   # Demo legacy
├── main.py                       # Entry FastAPI + legacy conciliación (no conectado al router público)
├── venv/, requirements.txt, ARQUITECTURA.md
```

---

## 6. Cómo correrla

```powershell
cd C:\Users\crist\dev\pyautomation\portafolio\conciliacion_bancaria
.\venv\Scripts\Activate.ps1
$env:PYTHONPATH = (Get-Location).Path
python -m uvicorn main:app --reload --port 8000
```

Abrir <http://127.0.0.1:8000>, elegir el análisis en el dropdown (EDA o Inventario), subir un CSV o XLSX, ver el resultado y descargar el Excel. Para el análisis de inventario, los parámetros (lead time, margen, ventana zombi, factor sobre-stock) aparecen automáticamente al seleccionar esa opción.

Para correr tests:
```powershell
python -m pytest tests/ -v
```

---

## 7. Comercialización

- **Cliente objetivo:** pyme de servicios o retail que recibe / genera planillas Excel recurrentes y necesita cruzar, validar o reportar a partir de ellas.
- **Pricing:** valor por ahorro (línea PyAutomation — 20–30% del ahorro anual, piso USD 250).
- **Pitch:** "subes tu archivo, eliges el análisis y recibes el reporte + el detalle de qué hizo el sistema para llegar ahí. No es una caja negra."
- **Demo:** versión limpia y versión sucia del dataset Kaggle de inventario para mostrar el detector en ambos extremos.

---

> Registrado en [[REGISTRO_TECNICO_PROYECTOS]] · [[GUIA_COMERCIAL_Y_MAR