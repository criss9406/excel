"""Punto de entrada de la app.

Monta archivos estaticos y el router del modulo de analisis.
"""
from pathlib import Path
import mimetypes

mimetypes.add_type('text/css', '.css')
mimetypes.add_type('application/javascript', '.js')

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from routes.analisisRoutes import router as analisis_router


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="PyAutomation - Analisis de Backoffice")

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(analisis_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
