# Privacidad y protección de datos — Fluidez Lectora

> Documento de trabajo técnico, no es asesoría legal. Antes de usar la app con alumnos, el colegio debe revisarlo con quien lleve su cumplimiento de la Ley 21.719 de protección de datos personales, que reemplaza a la Ley 19.628 y entra en vigencia en diciembre de 2026 según su régimen transitorio.

## Qué cambió respecto de lectura_app

En la versión de escritorio, el audio y los resultados quedaban en el PC del docente. Ahora:

- **El audio sale del PC.** Se guarda en Cloudflare R2.
- **Los resultados quedan en la base de Colegio Smart**, en Supabase.
- **El análisis de voz corre en el servidor** de Colegio Smart (VPS con Coolify).

Por eso el consentimiento que firmaron los apoderados para la versión local no cubre este uso: hay que pedir uno nuevo (ver el borrador al final).

## Qué datos se tratan

| Dato | Dónde queda | Quién lo ve |
|---|---|---|
| Grabación de la voz del alumno leyendo (dato personal de un menor; la voz puede identificarlo) | Cloudflare R2, bucket privado sin URL pública. Clave aleatoria `reading-audio/<institución>/<uuid>` | Docentes, directivos y equipo PIE de la institución, solo con URL firmada de 15 minutos |
| Transcripción y resultado palabra a palabra | Supabase (`reading_assessments.transcript`, `result`) | Igual que arriba |
| Métricas: PPM, precisión, categoría, fluidez, Rasinski, observación del docente | Supabase (`reading_assessments`) | Igual que arriba. Coordinación (directivos) ve el consolidado del colegio |
| Puntajes del modelo acústico (estudio de validación) | Supabase (`reading_assessments.prosody_model`) | Nadie en la interfaz. Solo los informes agregados del estudio, sin nombres (códigos E0001…) |
| Informe redactado con IA | Supabase (`reading_assessments.report`) | Igual que las métricas |
| Nombre, curso y RUT del alumno | No se copian: se leen de las tablas de Colegio Smart | Según los permisos de Colegio Smart |

## Flujo del audio

1. El navegador del docente pide una URL firmada a lectura-api y sube el audio **directo a R2**.
2. El worker descarga el audio a una carpeta temporal, lo analiza y **borra la carpeta** al terminar.
3. Para escucharlo, el navegador recibe otra URL firmada de 15 minutos.

## Encargados externos

| Proveedor | Para qué | Qué recibe |
|---|---|---|
| Cloudflare (R2) | Almacenar el audio | El archivo de audio |
| Supabase | Base de datos | Métricas, transcripciones y resultados |
| Anthropic (API de Claude) | Redactar informes, solo si el docente lo pide | **Solo cifras y listas de palabras leídas mal. Nunca nombres, RUT, curso ni audio** (ver `core/informes.py`) |

Estos proveedores pueden procesar los datos fuera de Chile (transferencia internacional). Hay que revisar sus condiciones y declararlo en la política de privacidad del colegio.

## Medidas de seguridad implementadas

- **Sesión y roles:** sesión de Colegio Smart (JWT firmado con HMAC-SHA en cookie HttpOnly) y protección CSRF. Solo DOCENTE, DIRECTIVO y EQUIPO_PIE, y solo si el plan incluye el permiso `lectura`.
- **Aislamiento por institución:** toda consulta se filtra por la institución del token. Los tests verifican que un colegio no vea datos de otro.
- **Edición restringida:** solo quien hizo la evaluación, o un directivo, puede modificarla.
- **Tokens viejos rechazados:** no valen los tokens emitidos antes de un cambio de contraseña.
- **Bucket privado:** el audio no tiene URL pública.

## Supresión de datos

- **Al eliminar un estudiante en Colegio Smart** se eliminan sus evaluaciones (FK `ON DELETE CASCADE`). Su audio se elimina con el barrido semanal `scripts/sweep_orphan_audio.py --apply`, que borra todo objeto de R2 sin evaluación asociada y con más de 24 horas.
- **Al descartar un borrador** se borran su fila y su audio.
- **Pendiente de decidir:** hoy no hay un plazo de conservación. Los audios y resultados quedan hasta que se elimine el estudiante. Recomendación: fijar un plazo para los audios, por ejemplo hasta el fin del año escolar siguiente, y conservar solo las métricas. Si se decide, se implementa como otro barrido programado.
- **Derechos del titular** (acceso, rectificación, supresión, oposición y portabilidad):
  - El historial de un alumno se consulta en Resultados → Por estudiante, y las métricas del curso se exportan a Excel.
  - Una evaluación guardada se corrige desde Evaluar → «Editar una evaluación guardada».
  - **Aún no hay acción en la interfaz** para exportar los datos y el audio de un solo alumno, ni para suprimir una evaluación ya guardada. Hoy eso lo hace un administrador en la base y en R2. Conviene agregarlo antes de recibir la primera solicitud.

## Borrador de consentimiento para apoderados

> Revisar y adaptar con el colegio antes de usar.

**Consentimiento para la evaluación de fluidez lectora**

Yo, ______________________, apoderado/a de ______________________, del curso ______, autorizo al colegio ______________________ a:

1. **Grabar la voz de mi pupilo/a** mientras lee en voz alta un texto, durante las evaluaciones de fluidez lectora del año ______ (hasta tres mediciones: inicio, mitad y fin de año).
2. **Guardar la grabación y los resultados** (velocidad, precisión, fluidez y observaciones del docente) en la plataforma Colegio Smart, con proveedores de almacenamiento en la nube que pueden estar fuera de Chile.
3. **Analizar la grabación con un programa automático** que transcribe la lectura. El docente revisa siempre el resultado.
4. **Usar las grabaciones, sin nombre, en un estudio interno** que compara la evaluación del docente con la del programa.

Entiendo que:

- Solo verán la grabación y los resultados los docentes, directivos y el equipo PIE del colegio.
- Si el docente pide un informe redactado con inteligencia artificial, se envían solo cifras, nunca el nombre, el RUT ni la grabación.
- Los resultados se usan para planificar apoyos de lectura y no constituyen un diagnóstico.
- Puedo pedir en cualquier momento ver, corregir o eliminar la grabación y los resultados, o retirar este consentimiento, escribiendo a ______________________. Retirarlo no afecta las notas ni la situación escolar de mi pupilo/a.
- Las grabaciones se conservarán hasta ______________________.

Firma: ______________________  Fecha: ____ / ____ / ______

☐ Autorizo los puntos 1 a 3.  ☐ Autorizo además el punto 4 (estudio interno).
