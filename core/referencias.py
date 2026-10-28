"""Referencias internacionales complementarias (no reemplazan al marco chileno elegido).

- Hasbrouck & Tindal (2017), normas de lectura oral en inglés (palabras correctas por minuto) por percentil,
  curso (1° a 6°) y momento del año. En español no son directamente comparables: se muestran como referencia.
- Escala Multidimensional de Fluidez de Rasinski (Zutell y Rasinski, 1991): 4 dimensiones de 1 a 4 (total 4-16).
"""
import numpy as np

PERCENTILES = [10, 25, 50, 75, 90]
# curso -> momento -> PPM en los percentiles 10, 25, 50, 75, 90 (None = no evaluado en ese momento)
HT_2017 = {
    1: {"inicio": None, "mitad": [9, 16, 29, 59, 97], "fin": [18, 34, 60, 91, 116]},
    2: {"inicio": [23, 36, 50, 84, 111], "mitad": [35, 59, 84, 109, 131], "fin": [43, 72, 100, 124, 148]},
    3: {"inicio": [40, 59, 83, 104, 134], "mitad": [62, 79, 97, 137, 161], "fin": [63, 91, 112, 139, 166]},
    4: {"inicio": [60, 75, 94, 125, 153], "mitad": [71, 95, 120, 143, 168], "fin": [83, 105, 133, 160, 184]},
    5: {"inicio": [64, 87, 121, 153, 179], "mitad": [84, 109, 133, 160, 183], "fin": [102, 119, 146, 169, 195]},
    6: {"inicio": [89, 112, 132, 159, 185], "mitad": [91, 116, 145, 166, 195], "fin": [91, 122, 146, 173, 204]},
}
FUENTE_HT = "Hasbrouck y Tindal (2017), normas en inglés"


def momento(fecha: str) -> str:
    """Momento del año escolar chileno según el mes: mar-may inicio, jun-ago mitad, sep-feb fin."""
    mes = int(fecha[5:7])
    return "inicio" if 3 <= mes <= 5 else "mitad" if 6 <= mes <= 8 else "fin"


def percentil_ht(ppm, nivel, fecha):
    """Percentil aproximado de Hasbrouck & Tindal. 7° y 8° usan 6° (la norma termina ahí).
    Devuelve (etiqueta como 'P45', '<P10' o '>P90', momento, ppm del percentil 50) o None si no aplica."""
    if ppm is None or nivel is None or not fecha or np.isnan(float(ppm)):
        return None
    curso = min(max(int(nivel), 1), 6)
    m = momento(fecha)
    fila = HT_2017[curso][m]
    if fila is None:
        return None
    if ppm < fila[0]:
        etiqueta = "<P10"
    elif ppm > fila[-1]:
        etiqueta = ">P90"
    else:
        etiqueta = f"P{round(float(np.interp(ppm, fila, PERCENTILES)))}"
    return etiqueta, m, fila[2]


# Escala Multidimensional de Fluidez (Rasinski): descriptores breves de los niveles 1 a 4
# dimensión -> 4 niveles (rótulo corto, descripción breve); textos cortos para caber en 4 columnas
RASINSKI = {
    "Expresión y volumen": [
        ("Sin expresión", "Lee solo por terminar; voz baja y plana."),
        ("Poca expresión", "Voz natural solo en algunos tramos."),
        ("Expresión parcial", "Voz natural casi siempre; algunos tramos planos."),
        ("Expresiva", "Ajusta expresión y volumen al sentido."),
    ],
    "Fraseo": [
        ("Palabra a palabra", "Monótono, sin agrupar palabras."),
        ("Grupos cortos", "De 2 o 3 palabras; corta el sentido."),
        ("Frases con cortes", "Algunas pausas a mitad de oración."),
        ("Por frases", "Respeta la puntuación y la entonación."),
    ],
    "Suavidad": [
        ("Muy entrecortada", "Pausas largas, titubeos y reintentos."),
        ("Entrecortada", "Se traba en palabras difíciles."),
        ("Casi continua", "Pocas interrupciones; las resuelve solo."),
        ("Continua", "Se autocorrige rápido, sin perder el hilo."),
    ],
    "Ritmo": [
        ("Muy lento", "Lento y con esfuerzo."),
        ("Lento", "Moderadamente lento."),
        ("Irregular", "Alterna tramos rápidos y lentos."),
        ("Adecuado", "Ritmo de conversación, constante."),
    ],
}


def interpretar_rasinski(puntajes):
    """puntajes: lista de 4 enteros 1-4. Total ≥ 10 = buen progreso; 8-9 = en desarrollo; < 8 = requiere apoyo."""
    if not puntajes or any(p is None for p in puntajes):
        return None
    total = sum(puntajes)
    estado = "Buen progreso" if total >= 10 else "En desarrollo" if total >= 8 else "Requiere apoyo en fluidez"
    return total, estado
