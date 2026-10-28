# lectura-api — Referencia de endpoints

Base: `https://lectura.colegiosmart.cl/api/lectura` (Netlify lo reenvía a lectura-api). Autenticación: la cookie `cs_session` de Colegio Smart. Toda escritura (`POST`, `PUT`, `PATCH`, `DELETE`) exige el header `X-XSRF-TOKEN` con el valor de la cookie `XSRF-TOKEN`; `apiFetch` de `@colegiosmart/api` ya lo envía.

Roles: **staff** = DOCENTE, DIRECTIVO o EQUIPO_PIE. **directivo** = solo DIRECTIVO.

Errores: `401` sin sesión válida, `403` sin rol o sin CSRF, `404` el recurso no existe en la institución del usuario, `400` validación (`{"detail": "mensaje"}`), `409` conflicto de estado, `422` cuerpo mal formado.

```bash
# ejemplo con curl (la cookie se copia del navegador)
C='cs_session=eyJ...; XSRF-TOKEN=abc'
curl -b "$C" https://lectura.colegiosmart.cl/api/lectura/courses
curl -b "$C" -H 'X-XSRF-TOKEN: abc' -H 'Content-Type: application/json' \
     -d '{"title":"El parque","level":5,"content":"La casa es grande."}' https://lectura.colegiosmart.cl/api/lectura/texts
```

## Catálogo

| Método | Path | Rol | Descripción |
|---|---|---|---|
| GET | `/me` | sesión | `{userId, email, institutionId, roleId}` |
| GET | `/config` | staff | Marcos (`frameworks`, igual a `config/escalas.json`), `defaultFramework`, `minimumAccuracyPct`, `levels`, `rasinski` `[{dimension, levels:[{label, description}]}]`, `engine`, `htSource` |
| GET | `/courses` | staff | `[{id, name: "5° Básico A", level: 5 \| null, studentCount}]`. `level` es null fuera de 1° a 8° básico |
| GET | `/courses/{id}/students?period=2026-10` | staff | `[{id, name, lastName, lastAssessment: {id, assessedAt, textTitle, wcpm} \| null, assessedInPeriod}]` |
| GET | `/texts?level=5` | staff | `[{id, title, level, content, wordCount, createdAt}]` |
| GET | `/texts/{id}` | staff | Texto + `assessmentCount` |
| POST | `/texts` | staff | Body `{title, level (1-8), content}` → `201` texto |
| PUT | `/texts/{id}` | staff | Mismo body. Las evaluaciones guardadas conservan su resultado |

## Evaluaciones

| Método | Path | Rol | Descripción |
|---|---|---|---|
| GET | `/assessments?courseId&studentId&period` | staff | Evaluaciones **completas**, en resumen |
| GET | `/assessments/drafts` | staff | Borradores del usuario actual ("Evaluaciones sin terminar") |
| POST | `/assessments` | staff | Crea el borrador (ver abajo) → `201` |
| POST | `/assessments/{id}/analyze` | autor o directivo | Encola el análisis → `202 {id, kind, status, error}`. `400` si el audio no está subido; `409` si ya está completa. Si ya hay un análisis en curso, devuelve ese mismo |
| GET | `/jobs/{id}` | staff | `{id, assessmentId, kind, status: pending\|running\|done\|error, error}` |
| GET | `/assessments/{id}` | staff | Vista completa (ver abajo) |
| PATCH | `/assessments/{id}` | autor o directivo | Autoguardado; solo cambia los campos enviados |
| POST | `/assessments/{id}/words/{index}` | autor o directivo | `{correct: bool}`: "Leída bien" o "Es error". Recalcula PCPM y precisión, y borra el PPM ajustado |
| POST | `/assessments/{id}/complete` | autor o directivo | `{generateReport: bool}`. Exige análisis y `expression`. Devuelve la vista + `reportError` |
| DELETE | `/assessments/{id}` | autor o directivo | Descarta un borrador y su audio → `204`. `409` si está completa o analizándose |

### POST /assessments

```json
{"studentId": 1000, "textId": 7, "period": "2026-10", "evaluatorName": "Prof. Rojas",
 "framework": "astoreca", "audioMime": "audio/webm;codecs=opus"}
```

Respuesta `201`:

```json
{"assessment": { "...vista..." }, "uploadUrl": "https://<cuenta>.r2.cloudflarestorage.com/...",
 "uploadHeaders": {"Content-Type": "audio/webm"}}
```

El navegador sube el audio con `fetch(uploadUrl, {method: "PUT", headers: uploadHeaders, body: blob})`, **sin** `credentials`, y luego llama a `/analyze`. Formatos aceptados: webm, mp4/m4a, ogg, wav y mp3. Errores: `404` si el estudiante o el texto no son de la institución; `400` si el curso no es de 1° a 8° básico o el formato no está soportado.

### Vista de una evaluación (GET, PATCH, words, complete)

```json
{
  "id": 1, "studentId": 1000, "studentName": "Ana Pérez", "courseId": 100, "courseName": "5° Básico A",
  "level": 5, "textId": 7, "textTitle": "El parque", "assessedAt": "2026-10-27T13:05:00+00:00",
  "period": "2026-10", "status": "draft", "analyzed": true,
  "framework": "astoreca", "evaluatorName": "Prof. Rojas", "evaluatorUserId": 10,
  "transcript": "la casa es grane …",
  "result": { "detalle": [{"ref": "grande.", "leido": "grane", "tipo": "sustitucion", "inicio": 1.5, "fin": 1.9}], "pcpm": 120.0, "...": "salida de core/analisis" },
  "wcpm": 130, "wcpmDetected": 120.0, "wcpmAdjusted": 130, "accuracyPct": 90.9, "errors": 1, "unexpectedPauses": 0,
  "category": "Media baja", "speedRange": "Bajo lo esperado", "expectedMinimumWcpm": 136,
  "expression": 4, "fluencyLabel": "Lectura unidades cortas", "fluencyRange": "Adecuado",
  "expectedFluency": "Lectura unidades cortas",
  "rasinski": [3, 3, 2, 4], "rasinski2": null, "rasinskiTotal": [12, "Buen progreso"],
  "observation": null, "report": null,
  "frameworkCoversLevel": true, "suggestedFramework": null,
  "doubtfulWords": [{"index": 7, "word": "rápido", "second": 3.5, "context": "«…el perro corre rápido por el parque…»"}],
  "htPercentile": {"band": "P35", "moment": "fin", "p50": 146},
  "audioUrl": "https://… (firmada, 15 min)",
  "job": {"id": 3, "kind": "analyze", "status": "done", "error": null}
}
```

`wcpm` es el PPM efectivo: el ajustado si existe y, si no, el detectado. Las palabras con `tipo: "revisar"` cuentan como correctas hasta que el docente decida. Los puntajes del modelo del estudio **nunca** se incluyen en esta vista.

### PATCH /assessments/{id}

Todos los campos son opcionales: `framework`, `expression` (1..N según el marco), `wcpmAdjusted` (`null` lo quita), `observation`, `evaluatorName`, `period`, `rasinski` y `rasinski2` (4 valores de 1 a 4 o `null`). Un campo desconocido responde `422`. La categoría de velocidad se recalcula en el servidor.

## Reportes

| Método | Path | Rol | Descripción |
|---|---|---|---|
| GET | `/reports/courses/{id}?period=` | staff | Curso · medición: `periods`, `period`, `previousPeriod`, `kpis {evaluated, enrolled, averageWcpm, averageDelta, pctSpeedAdequate, pctFluencyAdequate, belowInBoth}`, `distributions [{period, rows}]`, `groups [{key, label, action, frequency, n, pct}]`, `incomplete`, `rasinski`, `students` (ordenados por prioridad de apoyo) y `errors`. Sin datos: `{empty: true}` |
| GET | `/reports/courses/{id}/export?period=` | staff | Excel de la tabla de estudiantes |
| POST | `/reports/courses/{id}/synthesis?period=` | staff | Síntesis del curso con IA (texto Markdown); `502` si falla Claude |
| GET | `/reports/courses/{id}/texts?textId=` | staff | Curso · por texto: `texts [{textId, title, students, averageWcpm, averageAccuracyPct}]` y `detail {kpis, words, errors, distribution, students}` |
| GET | `/reports/students/{id}` | staff | Por estudiante: `history` (con `htPercentile`, `rasinski`, `report`), `radar {axes, max, series}`, `words`, `errors` |
| GET | `/reports/institution?period=` | directivo | Coordinación: `kpis`, `courses` (por curso: `courseName`, `level`, `framework`, `distribution`, promedios y evaluados), `evolution {periods, rows:[{level, values}]}`, `alerts`, `plan`, `students` |
| GET | `/reports/institution/export?period=` | directivo | Excel de coordinación |
| GET | `/reports/study` | directivo | Estudio de prosodia: `pairs`, `milestones`, `byCourse`, `withRasinski`, `metrics` (desde 30 lecturas) |
| GET | `/reports/study/progress.md` | directivo | Informe de avance, sin puntajes del modelo |
| GET | `/reports/study/final/{30\|100}.md` | directivo | Informe final; `400` si no se llegó al hito |
| GET | `/reports/study/data/{30\|100}.xlsx` | directivo | Datos anónimos del estudio |

Cada fila de `students` trae: `{assessmentId, studentId, name, courseName, wcpm, category, speedRange, fluency, fluencyRange, accuracyPct, delta, toReview, group, groupLabel, date, period, textTitle, errors}`.

Las filas de `distribution` (`{categoria, n, pct, rango, adecuado}`), `errors` (`{tipo, n, pct}`), `words` (`{palabra, errores, estudiantes, leido}`), `alerts` (`{titulo, texto, nivel}`) y `rasinski` (`{n, total_promedio, pct_buen_progreso, por_dimension, dimension_mas_baja}`) vienen tal cual de `core/reportes.py`.

## Salud

`GET /actuator/health` → `{"status": "UP"}`, sin autenticación.
