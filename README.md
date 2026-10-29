# lectura-api

Microservicio de **fluidez lectora** de Colegio Smart. Es la migración de `lectura_app` (Streamlit, un PC, SQLite) a la arquitectura de Colegio Smart:

```
lectura.colegiosmart.cl ── apps/lectura (monorepo app-colegio-smart, Netlify)
   │  _redirects:  /api/lectura/*  → api-lectura.colegiosmart.cl/api/lectura/*
   │               /api/*          → api-v2.colegiosmart.cl/api/*
   ▼  (mismo origen → la cookie cs_session y XSRF-TOKEN viajan solas)
lectura-api ── FastAPI, Docker en Coolify
   ├─ Login: valida el JWT de api-colegio-smart (mismo secreto, issuer y audience)
   ├─ Cursos y estudiantes: lee las tablas de Colegio Smart (solo lectura)
   ├─ Postgres de Supabase: misma base y mismo esquema, tablas reading_*
   ├─ Audios: R2 privado, subida y reproducción con URL firmada
   └─ Worker: análisis de voz en segundo plano, modelos cargados en memoria
```

## Qué se reutilizó de lectura_app

`core/` se copió casi entero y sus tests siguen pasando: análisis y alineación, escalas, motor guiado (wav2vec2), Whisper, prosodia, reportes, referencias, estudio de validación e informes con Claude. Cambios:

- `core/db.py` (SQLite) se eliminó: las consultas están en `app/repository.py`. `assessments_frame()` entrega las evaluaciones con las mismas columnas que esperaba `core/`.
- `core/estudio.py`: el cálculo del modelo oculto pasó a `app/worker.py` (antes leía rutas locales).
- `core/transcribir.py`: Whisper en int8 en CPU (`LECTURA_WHISPER_COMPUTE`), ~0,9 GB en vez de ~3 GB.

Lo que hacían las páginas de Streamlit (`app.py`) ahora está en `app/assessments.py` (pantalla de resultado) y `app/reports.py` (Resultados y Coordinación).

## Flujo de una evaluación

1. `POST /api/lectura/assessments` crea el borrador y devuelve `uploadUrl`.
2. El navegador hace `PUT` del audio a esa URL (directo a R2).
3. `POST /assessments/{id}/analyze` encola el análisis. La web consulta `GET /jobs/{id}` hasta `done` o `error`.
4. `GET /assessments/{id}` trae el resultado: lectura coloreada, palabras dudosas y la URL del audio.
5. El docente revisa: `POST /assessments/{id}/words/{i}` para cada palabra dudosa y `PATCH /assessments/{id}` para el autoguardado.
6. `POST /assessments/{id}/complete` guarda la evaluación, que desde ahí entra a los reportes, y encola el modelo oculto del estudio.

Endpoints completos: [docs/api-reference.md](docs/api-reference.md).

## Desarrollo

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt   # sin torch: los tests no cargan modelos
.venv/bin/python -m pytest tests -q
# misma suite de API sobre Postgres con la migración real (borra el esquema public de esa base):
TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:55432/postgres .venv/bin/python -m pytest tests/test_api.py -q
```

Servidor local: `cp .env.example .env`, completar los valores y ejecutar `.venv/bin/uvicorn app.main:app --reload`. Para analizar audio de verdad hay que instalar `requirements.txt` completo (incluye torch).

## Despliegue (Coolify)

1. **Base de datos:** ejecutar en orden `migrations/001_reading_tables.sql`, `002_reading_legacy_source.sql` y `003_reading_course_syntheses.sql` en Supabase. Van en la misma base y el mismo esquema que api-colegio-smart.
2. **Bucket R2 privado** para los audios, sin dominio público. CORS del bucket: permitir `PUT` y `GET` desde `https://lectura.colegiosmart.cl`, con el header `Content-Type`.
3. **Imagen:** `docker build -t lectura-api .`, que ya trae el modelo wav2vec2. Para incluir también Whisper: `--build-arg WITH_WHISPER=1`.
4. **Recursos:** límite de **3 GB de RAM** (el motor guiado usa ~2–2,5 GB) y 2 a 4 vCPU. Un minuto de audio tarda unos 10 a 30 s en CPU. Correr **un solo proceso**: el worker y los modelos viven en él.
5. **Variables:** ver `.env.example`. `JWT_SECRET`, `JWT_ISSUER` y `JWT_AUDIENCE` deben ser idénticas a las de api-colegio-smart.
6. **Health check:** `GET /actuator/health`.
7. **Permiso:** ejecutar `pnpm seed-permissions` en app-colegio-smart, que crea la clave `lectura`, y asignarla a los tipos de plan que incluyan el módulo. Los usuarios la reciben en su próximo inicio de sesión.
8. **Tarea programada (semanal):** `python scripts/sweep_orphan_audio.py --apply`, que borra de R2 los audios sin evaluación asociada.

## Migrar los datos de lectura_app (un PC por vez)

Cada docente tiene su base en `lectura_app/datos/lectura.db` y sus audios en `datos/audios/`. Se copian a un equipo con acceso a la base y a R2, y se ejecuta:

```bash
# 1. Simulación: no escribe nada y genera el reporte de emparejamiento
python scripts/migrate_lectura_app.py --sqlite lectura.db --institution-id 12 --audios audios --report emparejamiento.csv
# 2. Revisar emparejamiento.csv: completar student_id donde diga "ambiguo" o "sin pareja"
# 3. Importar
python scripts/migrate_lectura_app.py --sqlite lectura.db --institution-id 12 --audios audios \
    --mapping emparejamiento.csv --evaluator-user-id 34 --apply
```

- **Emparejamiento:** el curso local ("5°A") se busca por nivel y letra. Dentro de él, el nombre tiene que coincidir exacto (sin tildes ni mayúsculas) o con las mismas palabras en otro orden. Si no aparece, se acepta un nombre único en todo el colegio (alumnos que ya subieron de curso).
- **Qué se importa:** las evaluaciones completas, los textos usados y los audios. Los borradores no se importan.
- **Re-ejecutable:** lo ya importado se salta (`source`/`source_id`, migración 002).
- **El SQLite se abre en solo lectura**, así que el archivo del docente no se modifica.

## Seguridad y privacidad

- Todo endpoint exige sesión de Colegio Smart, el permiso `lectura` en el plan (salvo Admin) y rol de institución: DOCENTE, DIRECTIVO o EQUIPO_PIE. Coordinación, solo DIRECTIVO; el estudio de validación de prosodia, solo Admin de plataforma (con institución en su cuenta). Los datos se filtran siempre por la `institutionId` del token.
- Se rechazan los tokens emitidos antes del último cambio de contraseña, igual que `JwtAuthFilter`.
- Protección CSRF con doble envío (`XSRF-TOKEN` / `X-XSRF-TOKEN`), igual que api-colegio-smart.
- Solo quien hizo la evaluación, o un directivo, puede modificarla.
- A Claude solo se envían cifras y listas de palabras, nunca nombres.
- **El audio ahora sale del PC.** Hay que actualizar el consentimiento de los apoderados y revisar la Ley 21.719 antes de usarlo con alumnos. El inventario de datos, los flujos y un borrador de consentimiento están en [docs/privacidad.md](docs/privacidad.md).

## Pendientes

- Plazo de conservación de los audios y acciones en la interfaz para exportar o suprimir los datos de un alumno (ver [docs/privacidad.md](docs/privacidad.md)).
- La configuración del motor (`config/motor.json`) es global del servicio, ya no se cambia desde la interfaz.
