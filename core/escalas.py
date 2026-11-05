"""Carga de marcos de referencia de velocidad y fluidez lectora, y clasificación por PCPM/PPM."""
import json
from pathlib import Path

RUTA_DEFECTO = Path(__file__).resolve().parent.parent / "config" / "escalas.json"


def cargar_escalas(ruta: str | None = None) -> dict:
    with open(ruta or RUTA_DEFECTO, encoding="utf-8") as f:
        return json.load(f)


def adecuado_desde(marco: dict, nivel) -> str:
    """Categoría desde la que la velocidad es adecuada; un marco puede fijarla distinta en un nivel."""
    return (marco.get("adecuado_desde_por_nivel") or {}).get(str(nivel), marco["adecuado_desde"])


# Equivalencia entre las escalas de fluidez (1-based) al cambiar el marco de una evaluación ya hecha.
# shortcut: aproximada, por la descripción de cada nivel; el docente puede corregir la categoría después.
CONVERSION_FLUIDEZ = {
    ("mineduc", "astoreca"): {1: 3, 2: 4, 3: 4, 4: 5},
    ("astoreca", "mineduc"): {1: 1, 2: 1, 3: 1, 4: 2, 5: 4},
}


def convertir_fluidez(valor: int | None, de: str, a: str) -> int | None:
    if valor is None or de == a:
        return valor
    return CONVERSION_FLUIDEZ.get((de, a), {}).get(valor)


def clasificar(pcpm: float, nivel: int, marco: dict) -> str | None:
    # Las escalas van de mayor a menor mínimo: gana el primer tramo que se cumple.
    for nombre, minimo in marco["niveles"].get(str(nivel), []):
        if pcpm >= minimo:
            return nombre
    return None


def rango_velocidad(categoria: str | None, nivel: int, marco: dict) -> str | None:
    orden = [nombre for nombre, _ in marco["niveles"].get(str(nivel), [])]
    desde = adecuado_desde(marco, nivel)
    if categoria not in orden or desde not in orden:
        return None
    # La lista va de mayor a menor: lo adecuado está en la misma posición o antes.
    adecuado = orden.index(categoria) <= orden.index(desde)
    return "Adecuado" if adecuado else "Bajo lo esperado"


def rango_fluidez(fluidez: int | None, nivel: int, marco: dict) -> str | None:
    minima = (marco.get("fluidez_minima") or {}).get(str(nivel))
    if fluidez is None or minima is None:
        return None
    return "Adecuado" if fluidez >= minima else "Bajo lo esperado"
