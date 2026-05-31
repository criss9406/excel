# Arquitectura del Proyecto — Plantilla

Este documento describe la arquitectura, el stack y las convenciones utilizadas en este proyecto, pensado como **esqueleto reutilizable** para iniciar nuevas aplicaciones web con la misma base técnica.

---

## 1. Stack tecnológico

### Lenguaje
- **Python 3.10+**

### Framework web
- **FastAPI** — framework web asíncrono, basado en ASGI, con validación de tipos vía Pydantic.

### Servidor de aplicación
- **Uvicorn** — servidor ASGI de desarrollo y workers en producción.
- **Gunicorn** — gestor de procesos en producción, usando workers de Uvicorn (`uvicorn.workers.UvicornWorker`).

### Capa de presentación (server-side rendering)
- **Jinja2** — motor de plantillas HTML.
- **HTML5 + CSS** estáticos servidos por el propio framework.
- **MarkupSafe** — escape seguro de HTML inyectado dinámicamente desde plantillas.

### Persistencia
- **PostgreSQL** — base de datos relacional principal.
- **SQLAlchemy 2.x** — ORM y motor de conexión.
- **Alembic** — herramienta de migraciones versionadas.
- **psycopg2-binary** — driver PostgreSQL.

### Utilidades / I/O
- **openpyxl** — lectura/escritura de archivos Excel (`.xlsx`).
- **reportlab** — generación de PDFs.
- **httpx** — cliente HTTP asíncrono.
- **python-multipart** — parsing de formularios `multipart/form-data`.
- **python-dotenv** — carga de variables de entorno desde archivos `.env` en desarrollo.

### Despliegue
- **Railway** — plataforma PaaS donde corre la aplicación.
- **Procfile** — describe el proceso `web` que Railway ejecuta al desplegar.
- Variables de entorno (`DATABASE_URL`, `PORT`) inyectadas automáticamente por Railway.

---

## 2. Estructura de carpetas

```
proyecto/
├── main.py                 # Punto de entrada de la app (FastAPI app + mounts + routers)
├── database.py             # Configuración de motor SQLAlchemy + dependencia get_db()
├── models.py               # Definición de modelos ORM (tablas)
├── config.json             # Configuración estática no-secreta de la aplicación
├── requirements.txt        # Dependencias Python
├── alembic.ini             # Configuración de Alembic
├── Procfile                # Comando de arranque para PaaS
│
├── routes/                 # Capa de presentación / controladores HTTP
│   └── <recurso>Routes.py  # APIRouter por recurso/dominio
│
├── services/               # Capa de lógica de negocio
│   └── <recurso>Service.py # Funciones puras de negocio + acceso a modelos
│
├── templates/              # Plantillas Jinja2
│   ├── base.html           # Layout base (header, blocks de contenido y scripts)
│   └── <recurso>/          # Subcarpeta por recurso
│       └── *.html
│
├── static/                 # Recursos estáticos servidos en /static
│   └── css/
│       └── styles.css
│
├── migrations/             # Migraciones gestionadas por Alembic
│   ├── env.py              # Configura target_metadata desde Base.metadata
│   ├── script.py.mako
│   └── versions/           # Migraciones generadas (una por revisión)
│
└── data/                   # Datos auxiliares estáticos (semillas, fixtures, etc.)
```

---

## 3. Arquitectura por capas

El proyecto sigue una **arquitectura en capas** clásica, monolítica, con separación clara entre presentación, lógica de negocio y persistencia.

```
┌─────────────────────────────────────────────────────┐
│  Cliente (navegador)                                │
└──────────────────────────┬──────────────────────────┘
                           │ HTTP (HTML / JSON)
┌──────────────────────────▼──────────────────────────┐
│  main.py — FastAPI app                              │
│  · Monta /static                                    │
│  · Incluye routers                                  │
└──────────────────────────┬──────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│  routes/ — Capa de presentación                     │
│  · APIRouter por recurso                            │
│  · Renderiza Jinja2 o devuelve JSON/Response        │
│  · Inyecta dependencias (get_db, sesión, etc.)      │
│  · Filtros Jinja2 personalizados                    │
└──────────────────────────┬──────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│  services/ — Capa de lógica de negocio              │
│  · Funciones que reciben (Session, datos)           │
│  · Reglas de negocio, transformaciones, I/O         │
│  · Sin conocimiento de HTTP                         │
└──────────────────────────┬──────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│  models.py + database.py — Capa de persistencia     │
│  · Modelos ORM declarativos (Base = declarative_b.) │
│  · SessionLocal + engine                            │
└──────────────────────────┬──────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│  PostgreSQL                                         │
└─────────────────────────────────────────────────────┘
```

### Reglas de dependencia
- `routes/` puede importar `services/` y `database.py`.
- `services/` puede importar `models.py` y `database.py`.
- `models.py` solo conoce `database.py` (`Base`).
- **Las capas inferiores no conocen las superiores.**

---

## 4. Componentes clave

### `main.py`
Punto único de entrada. Su responsabilidad es:
- Construir la instancia de `FastAPI`.
- Montar archivos estáticos en `/static`.
- Incluir los `APIRouter` de cada módulo en `routes/`.

Debe mantenerse mínimo: nada de lógica de negocio aquí.

### `database.py`
- Lee `DATABASE_URL` desde el entorno (con normalización `postgres://` → `postgresql://`).
- Crea el `engine` y `SessionLocal`.
- Expone `Base = declarative_base()` para los modelos.
- Provee la dependencia `get_db()` para inyectar sesión por request en FastAPI.

### `models.py`
- Define las tablas como clases que heredan de `Base`.
- Usa tipos de SQLAlchemy (`Column`, `Integer`, `String`, `JSON`, `ForeignKey`, etc.).
- Mantiene los modelos en un único archivo cuando son pocos; dividir en submódulos si crece.

### `routes/<recurso>Routes.py`
- Define un `APIRouter` por recurso o dominio funcional.
- Usa `Jinja2Templates` para renderizar HTML.
- Registra **filtros Jinja2 personalizados** (formato de moneda, fechas, transformaciones de texto, etc.).
- Inyecta la sesión vía `Depends(get_db)`.
- Delega cualquier lógica no trivial a `services/`.

### `services/<recurso>Service.py`
- Contiene la lógica de negocio.
- Recibe `Session` y datos planos (dicts, primitivos), nunca objetos `Request`.
- Hace I/O auxiliar (lectura de `config.json`, generación de archivos, etc.).
- Devuelve estructuras serializables (dicts, listas).

### `templates/`
- `base.html` define el layout (header, navegación, bloques `content` y `scripts`).
- Cada recurso tiene su subcarpeta con plantillas que extienden `base.html`.

### `static/`
- CSS, JS y assets servidos directamente. Sin pipeline de build.

### `migrations/`
- Gestionado por Alembic.
- `env.py` importa `Base` y los modelos para que `target_metadata = Base.metadata` recoja todo el esquema y permita autogeneración (`alembic revision --autogenerate`).

### `config.json`
- Configuración **no-sensible** versionada en el repo (parámetros por defecto, datos de la organización, plantillas).
- Los **secretos** (credenciales, URLs de DB) van siempre por variables de entorno.

---

## 5. Flujo de una petición

1. El cliente envía una petición HTTP a una ruta.
2. FastAPI la enruta al `APIRouter` correspondiente.
3. El handler en `routes/` resuelve dependencias (sesión DB, formularios, query params).
4. Llama a una o más funciones de `services/` con los datos ya parseados.
5. El service ejecuta la lógica, consulta/persiste vía SQLAlchemy y devuelve datos planos.
6. El handler renderiza una plantilla Jinja2 o devuelve JSON/`Response`.
7. La sesión DB se cierra automáticamente (gracias al `yield` en `get_db()`).

---

## 6. Configuración y entornos

| Aspecto             | Mecanismo                                            |
|---------------------|------------------------------------------------------|
| Secretos            | Variables de entorno (`DATABASE_URL`, etc.)          |
| Config no-secreta   | `config.json` versionado                             |
| Desarrollo local    | `.env` cargado vía `python-dotenv`                   |
| Producción          | Variables definidas en Railway (panel del servicio)  |
| Puerto              | `$PORT` (inyectado por Railway)                      |
| Base de datos       | PostgreSQL provisto como plugin/servicio en Railway  |

---

## 7. Migraciones de base de datos

Flujo estándar con Alembic:

```bash
# Crear nueva revisión a partir de cambios en models.py
alembic revision --autogenerate -m "descripcion"

# Aplicar migraciones pendientes
alembic upgrade head

# Revertir la última
alembic downgrade -1
```

`migrations/env.py` debe importar `Base` y los modelos para que la autogeneración detecte cambios en el esquema.

---

## 8. Despliegue (Railway)

La aplicación se despliega en **Railway**. El servicio detecta el `Procfile` y ejecuta el proceso `web` allí definido.

### Procfile
Arranca Gunicorn con workers Uvicorn escuchando en el puerto inyectado por Railway:

```
web: gunicorn main:app -w <N> -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT
```

### Configuración del servicio en Railway
1. Conectar el repositorio al servicio de Railway.
2. Añadir un plugin **PostgreSQL** dentro del mismo proyecto: Railway expondrá `DATABASE_URL` automáticamente al servicio web.
3. Definir las variables de entorno restantes en el panel del servicio.
4. Configurar un **release/deploy command** que ejecute las migraciones antes de levantar la app:
   ```
   alembic upgrade head
   ```
5. Cada `git push` a la rama vinculada dispara un nuevo build y deploy.

### Notas
- Railway entrega `DATABASE_URL` con esquema `postgres://`; `database.py` lo normaliza a `postgresql://` para que SQLAlchemy lo acepte.
- `$PORT` lo asigna Railway en cada deploy: no fijarlo manualmente.

---

## 9. Seguridad

Consideraciones que deben acompañar a cualquier proyecto que se construya sobre este esqueleto.

### Gestión de secretos
- Nada de credenciales, tokens ni URLs con contraseña en el repositorio.
- Los secretos se inyectan por variables de entorno (panel de Railway en producción, archivo `.env` local nunca versionado).
- `config.json` solo para parámetros **no sensibles**; debe poder publicarse sin riesgo.
- `.gitignore` debe excluir `.env`, `venv/`, `__pycache__/` y cualquier export local de datos.

### Modelo de amenazas
- Definir explícitamente si la aplicación es **interna** (red de confianza) o **pública** antes de empezar. Este criterio cambia qué controles son obligatorios.
- Documentar qué datos protege la app (personales, financieros, internos) para dimensionar los controles y los registros de auditoría.

### Autenticación y autorización
- Decisión explícita: si la app no tiene autenticación, debe quedar registrado por qué (uso interno, despliegue tras VPN, etc.).
- Cuando exista, separar **autenticación** (quién es) de **autorización** (qué puede hacer); esta última debe vivir en la capa de servicios, no en plantillas ni en rutas.

### Defensas heredadas del stack (mantenerlas activas)
- **Inyección SQL**: usar siempre el ORM o consultas parametrizadas. Prohibido construir SQL por concatenación o f-strings.
- **XSS**: Jinja2 escapa por defecto. Cualquier uso de `Markup` / `| safe` debe justificarse y limitarse a contenido ya saneado.
- **Validación de entrada**: tipar parámetros de rutas con Pydantic / tipos de FastAPI; los formularios HTML deben validarse en el servicio, no confiar en validación de cliente.

### Defensas que el stack NO da gratis
Evaluar caso a caso e incorporar cuando apliquen:
- **CSRF** en formularios HTML autenticados (FastAPI no incluye protección por defecto).
- **Rate limiting** en endpoints públicos (login, formularios, generación de archivos costosa).
- **Headers de seguridad**: `Content-Security-Policy`, `Strict-Transport-Security`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`. Aplicables vía middleware.
- **CORS**: configurar de forma restrictiva si se expone una API consumida desde otro origen; no usar `*` en producción.
- **Cookies de sesión**: marcar `Secure`, `HttpOnly` y `SameSite` cuando se introduzca autenticación.

### Transporte
- HTTPS/TLS lo termina Railway en el dominio público; la aplicación no debe gestionar certificados.
- No exponer la app por HTTP plano. Forzar redirección a HTTPS si Railway no lo hace por defecto en el dominio usado.

### Base de datos
- Credenciales con **privilegio mínimo**: el usuario de la app no debe ser superusuario.
- La instancia de PostgreSQL **no debe exponerse a internet** salvo durante operaciones puntuales; Railway permite mantenerla en red privada del proyecto.
- Verificar política de **backups/snapshots** de Railway según el plan contratado.
- Nunca registrar consultas que incluyan datos personales o secretos.

### Manejo de errores y logging
- En producción, **nunca devolver tracebacks** ni mensajes internos al cliente. FastAPI debe correr con respuestas de error genéricas.
- Logs sin PII (nombres, RUTs, correos) salvo necesidad explícita y justificada.
- Diferenciar logs de aplicación (negocio) de logs de seguridad (autenticación, cambios de permisos, accesos denegados).

### Cadena de dependencias
- Fijar versiones en `requirements.txt` (idealmente con un lockfile reproducible).
- Auditar periódicamente con herramientas tipo `pip-audit` o el escáner de Dependabot/GitHub.
- Reducir el set de dependencias al mínimo: cada librería es superficie de ataque.

### Subida y generación de archivos
- Validar tipo y tamaño de los archivos subidos (`python-multipart` no lo hace por sí solo).
- Generación de PDFs / Excel: cuidado con plantillas que interpolan entrada del usuario sin sanear (puede derivar en inyección de fórmulas en `.xlsx` o contenido malicioso en PDF).
- Servir archivos generados por endpoint controlado, nunca desde rutas que permitan path traversal.

### Checklist mínimo antes de pasar a producción
- [ ] `.env` y secretos fuera del repositorio.
- [ ] `DATABASE_URL` y demás variables configuradas en Railway.
- [ ] DB con usuario de privilegio mínimo y sin acceso público.
- [ ] HTTPS forzado en el dominio.
- [ ] Modo debug desactivado; sin tracebacks al cliente.
- [ ] Decisión documentada sobre auth/CSRF/rate limiting/CORS.
- [ ] Dependencias auditadas y fijadas.
- [ ] Backups verificados.

---

## 10. Convenciones

- **Nombres de archivos en `routes/` y `services/`**: `<recurso>Routes.py` / `<recurso>Service.py` (camelCase del recurso + sufijo).
- **Un router por dominio funcional**.
- **Filtros Jinja2** se registran en el módulo de routes que los necesita.
- **Sin lógica de negocio en plantillas ni en `main.py`**.
- **Sin acceso directo a la DB desde `routes/`**: siempre vía `services/`.
- **Tipos de columnas flexibles**: usar `JSON` para estructuras anidadas que no requieren consultas relacionales.
- **Datos de prueba locales**: Todo proyecto debe incluir un archivo `seed*.py` (ej. `seed.py`) para generar datos ficticios que faciliten las pruebas locales. Este archivo, junto con notas de desarrollo interno (`status.md`, `ARQUITECTURA.md`), **debe estar siempre incluido en `.gitignore`** para evitar que código de prueba o documentación técnica interna se filtre y sea subida a plataformas de producción como Railway.

---

## 11. Cómo replicar este esqueleto

1. Copiar la estructura de carpetas vacía (sin `routes/*.py`, `services/*.py`, `templates/<recurso>/`, `migrations/versions/*`).
2. Copiar `main.py`, `database.py`, `templates/base.html`, `Procfile`, `alembic.ini`, `requirements.txt`.
3. Definir los modelos del nuevo dominio en `models.py`.
4. Inicializar Alembic (`alembic init migrations` si no existe) y editar `env.py` para apuntar a `Base.metadata`.
5. Crear el primer router en `routes/` y registrarlo en `main.py`.
6. Crear el service correspondiente en `services/`.
7. Configurar `DATABASE_URL` en el entorno y generar la primera migración.
