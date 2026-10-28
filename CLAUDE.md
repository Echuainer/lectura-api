# lectura-api — Guía para Claude Code

Microservicio de fluidez lectora de Colegio Smart (Python 3.12 + FastAPI). Arquitectura y despliegue en [README.md](README.md).

## Documentación de endpoints

Todos los endpoints están documentados en [`docs/api-reference.md`](docs/api-reference.md). Cada vez que se cree, modifique o elimine un endpoint, actualizar ese archivo en la misma sesión.

## Código

- `core/` viene de lectura_app: identificadores y comentarios en español. No cambiar sus nombres; sus tests (`tests/test_analisis.py`, `test_reportes.py`, etc.) son el contrato.
- `app/` es código nuevo: identificadores en inglés (como api-colegio-smart). Los mensajes al usuario van en español.
- Las estadísticas se calculan siempre en código (`core/reportes.py`, `core/estudio.py`). La IA solo redacta, y nunca recibe nombres.
- El JSON de la API usa camelCase. Los objetos anidados que produce `core/` conservan sus claves en español.

## Base de datos

- Misma base y mismo esquema que api-colegio-smart. Las tablas propias llevan el prefijo `reading_`. Sin auto-DDL: cada cambio va como un archivo nuevo en `migrations/NNN_descripcion.sql`, y `app/db.py` se actualiza a la par.
- SQL siempre en inglés. Cada columna FK (`_id`) lleva su `CREATE INDEX idx_<tabla>_<columna>`.
- Las tablas de Colegio Smart (`students`, `courses`, `cycles_types_levels`, `users`, `institutions`) son **solo lectura** aquí.

## Seguridad de endpoints

Todo endpoint usa `Depends(staff)`, `Depends(directors)` o `require_role(...)` de `app/security.py`, y filtra por `ctx.institution_id`. Nunca dejar un endpoint sin control de acceso.

## Tests

```bash
.venv/bin/python -m pytest tests -q
TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:55432/postgres .venv/bin/python -m pytest tests/test_api.py -q
```

La segunda línea corre la API sobre Postgres con las migraciones reales. Usarla al cambiar SQL.
