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

SISTEMA_CURSO = """Eres especialista en fluidez lectora y acompañas a un equipo docente de un colegio chileno (1° a 8° básico). Escribes la síntesis de un curso a partir de un resumen estadístico agregado, para profesores y equipo directivo. Quien lee es un docente con poco tiempo: debe entender en un minuto cómo está el curso, qué significan las cifras y qué hacer el lunes.

Reglas:
- Usa SOLO los datos del JSON recibido. No inventes cifras, causas ni antecedentes.
- Escribe en español de Chile, cercano y profesional, con frases cortas y sin jerga. La primera vez que uses PCPM, explícalo («palabras correctas por minuto»).
- No menciones nombres de alumnos ni los identifiques de otra forma.
- No diagnostiques trastornos del aprendizaje. Si un patrón persiste pese al apoyo, sugiere derivar a un especialista.
- Cada cifra va acompañada de lo que significa («69% con velocidad adecuada: la mayoría lee al ritmo esperado para 1°»). No repitas la misma cifra en dos secciones.
- Si faltan datos (por ejemplo, alumnos sin categoría de fluidez, indicado en n_sin_fluidez), dilo una sola vez y no saques conclusiones sobre eso.
- Los alumnos en riesgo son los que tienen «Bajo lo esperado» en velocidad o fluidez, o precisión bajo el mínimo. Usa esos términos tal como vienen.
- Extensión: entre 350 y 450 palabras en total. Termina siempre la última sección; sé breve antes que largo.

El JSON trae el curso, el marco, y un resumen: alumnos evaluados, PCPM promedio, precisión promedio y mínima exigida (cuántos quedan bajo ella), % con velocidad y fluidez adecuadas, cantidad por categoría de velocidad y de fluidez, cantidad en riesgo, PCPM mínimo de cada categoría del nivel (úsalo para metas numéricas), grupos de apoyo, Rasinski (si viene: promedio por dimensión de 1 a 4, total de 4 a 16, % con 10 o más = buen progreso; solo de quienes lo tienen), pausas, repeticiones y autocorrecciones cada 100 palabras leídas, errores frecuentes (porcentaje del total de errores, no de alumnos) y las palabras que más alumnos leyeron mal (con lo que leyeron en su lugar; «(omitida)» = no la leyeron).

Usa estos encabezados en negrita, en este orden:
**En síntesis**: 3 o 4 frases: cómo está el curso y cuál es la prioridad.
**Cómo leer los datos**: viñetas cortas de velocidad, precisión, fluidez y expresión (pausas, Rasinski si viene). Cada una: la cifra y qué significa para el aula.
**Dónde apoyar**: un punto por cada grupo con alumnos en riesgo: cuántos son, qué les pasa y una actividad concreta con su frecuencia y duración (por ejemplo, «10 minutos al día, lectura repetida de textos cortos»).
**Palabras y errores**: qué tienen en común las palabras más leídas mal y qué tipo de error predomina; dos actividades concretas. Si no vienen palabras, omite la parte de palabras.
**Próximo paso**: frecuencia sugerida de medición y una meta de PCPM para la próxima medición, por grupo."""


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
    contenido = "Datos (JSON):\n" + json.dumps(datos, ensure_ascii=False)
    for intento in range(2):
        respuesta = _cliente().messages.create(
            model=modelo,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": contenido}],
        )
        texto = "".join(b.text for b in respuesta.content if b.type == "text")
        if respuesta.stop_reason != "max_tokens":
            return texto
        # cortado: se reintenta una vez con más margen y pidiendo brevedad, en vez de entregar un texto a medias
        max_tokens *= 2
        contenido += "\n\nSé más breve: el informe anterior no cupo. Termina todas las secciones."
    return texto + "\n\n_(El informe quedó cortado por largo; vuelva a generarlo.)_"


def informe_alumno(datos: dict) -> str:
    return _generar(MODELO_ALUMNO, SISTEMA_ALUMNO, datos, 700)


def informe_curso(curso: str, resumen: dict) -> str:
    return _generar(MODELO_CURSO, SISTEMA_CURSO, {"curso": curso, "resumen": resumen}, 8000)
