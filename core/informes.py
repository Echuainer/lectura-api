"""Redacción de informes con la Claude API. Solo recibe datos agregados, nunca nombres."""
import json
import os

import anthropic

from core import escalas

MODELO_ALUMNO = "claude-haiku-5-5"
MODELO_CURSO = "claude-sonnet-5-5"
MAX_LISTA = 15

SISTEMA_ALUMNO = """Eres especialista en fluidez lectora y acompañas a docentes de colegios chilenos (5° a 8° básico). Redactas el informe de lectura en voz alta de un alumno, para su profesor y, si corresponde, para sus apoderados.

Reglas:
- Usa SOLO los datos del JSON recibido. No inventes cifras, causas ni antecedentes.
- Escribe en español de Chile, con tono profesional, claro y respetuoso.
- No menciones nombres ni datos que identifiquen al alumno.
- No diagnostiques trastornos del aprendizaje (por ejemplo, dislexia). Describe el desempeño lector. Si hay patrones de error persistentes, sugiere evaluación con un especialista (psicopedagogo, fonoaudiólogo o neurólogo infantil).
- Máximo 180 palabras en total.

El JSON contiene: nivel (curso, 5 a 8), marco (marco de referencia usado), categoria (velocidad según ese marco), rango_velocidad y rango_fluidez ("Adecuado" o "Bajo lo esperado"; null si no se puede determinar), expresion (valor de la escala de fluidez del marco; null si no se evaluó) y fluidez_categoria (su descripción en el marco), metricas (pcpm = palabras correctas por minuto; ppm = palabras leídas por minuto; precision_pct; errores; pausas_inesperadas; repeticiones; autocorrecciones; y otras cifras), sustituciones (palabra del texto y palabra leída en su lugar) y omisiones (palabras del texto que no se leyeron).

Los rangos vienen calculados: úsalos tal cual, sin recalcularlos ni proponer otros umbrales. "Bajo lo esperado" significa bajo lo esperado para el curso según el marco indicado.

Usa estos tres encabezados, en negrita y en este orden:
**Diagnóstico**: velocidad (PCPM, categoría y rango), precisión y fluidez (fluidez_categoria, o expresion si no viene). Describe el desempeño, nunca un trastorno.
**Patrones de error**: qué tipos de error predominan (sustituciones, omisiones, repeticiones, pausas) y qué sugieren. Cita hasta dos ejemplos de las listas.
**Sugerencias**: exactamente 3, concretas y realizables en el aula o en casa."""

SISTEMA_CURSO = """Eres especialista en fluidez lectora y asesoras a un equipo docente de un colegio chileno (5° a 8° básico). Redactas el informe de un curso a partir de un resumen estadístico agregado, para profesores y equipo directivo.

Reglas:
- Usa SOLO los datos del JSON recibido. No inventes cifras, causas ni antecedentes.
- Escribe en español de Chile, con tono profesional, claro y respetuoso.
- No menciones nombres de alumnos ni los identifiques de otra forma.
- No diagnostiques trastornos del aprendizaje. Si hay patrones persistentes en un grupo, sugiere derivar a evaluación con especialistas.
- Están en riesgo los alumnos con rango "Bajo lo esperado" en velocidad o fluidez, o con precisión bajo el mínimo. Usa esos términos tal como vienen en el resumen.
- Máximo 350 palabras en total.

El JSON trae el curso, el marco de referencia y un resumen agregado: cantidad de alumnos evaluados, promedio de PCPM (palabras correctas por minuto), precisión promedio y mínima exigida (con cuántos quedan bajo ella), porcentaje con velocidad y fluidez adecuadas, cantidad por categoría de velocidad y de fluidez, cantidad en riesgo, PCPM mínimo de cada categoría para el nivel (úsalo para metas numéricas), grupos de apoyo, escala de Rasinski de prosodia (si viene: promedio por dimensión de 1 a 4, total de 4 a 16, % con 10 o más = buen progreso; solo de quienes la tienen registrada, menciónalo como complemento de la fluidez) y errores frecuentes (porcentaje sobre el total de errores, no cantidad de alumnos).

Usa estos tres encabezados, en negrita y en este orden:
**Panorama**: cómo está el curso en velocidad, fluidez y precisión, y qué proporción está en riesgo.
**Grupos de apoyo**: un grupo por cada categoría de velocidad o de fluidez con alumnos en riesgo; indica cuántos alumnos tiene cada uno y qué apoyo requiere.
**Medidas para el colegio**: frecuencia sugerida de medición y metas de PCPM para la próxima medición, por grupo."""


def _cliente() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("Falta ANTHROPIC_API_KEY en el archivo .env")
    return anthropic.Anthropic()


def construir_datos_alumno(nivel, metricas: dict, categoria, expresion, detalle: list,
                          marco: dict | None = None) -> dict:
    """Arma el JSON del alumno: solo cifras y listas de palabras, sin nombre."""
    datos = {
        "nivel": nivel,
        "categoria": categoria,
        "expresion": expresion,
        # Solo cifras y booleanos: "detalle" y cualquier texto quedan fuera.
        "metricas": {k: v for k, v in metricas.items() if isinstance(v, (int, float, bool))},
        "sustituciones": [
            {"texto": d["ref"], "leido": d["leido"]} for d in detalle if d["tipo"] == "sustitucion"
        ][:MAX_LISTA],
        "omisiones": [d["ref"] for d in detalle if d["tipo"] == "omision"][:MAX_LISTA],
    }
    if marco:
        datos |= {
            "marco": marco["nombre"],
            "rango_velocidad": escalas.rango_velocidad(categoria, nivel, marco),
            "rango_fluidez": escalas.rango_fluidez(expresion, nivel, marco),
            "fluidez_categoria": marco["fluidez"][expresion - 1] if expresion else None,
        }
    return datos


def _generar(modelo: str, sistema: str, datos: dict, max_tokens: int) -> str:
    respuesta = _cliente().messages.create(
        model=modelo,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": "Datos (JSON):\n" + json.dumps(datos, ensure_ascii=False)}],
    )
    texto = "".join(b.text for b in respuesta.content if b.type == "text")
    if respuesta.stop_reason == "max_tokens":
        texto += "\n\n_(El informe quedó cortado por largo; vuelva a generarlo.)_"
    return texto


def informe_alumno(datos: dict) -> str:
    return _generar(MODELO_ALUMNO, SISTEMA_ALUMNO, datos, 700)


def informe_curso(curso: str, resumen: dict) -> str:
    return _generar(MODELO_CURSO, SISTEMA_CURSO, {"curso": curso, "resumen": resumen}, 3000)
