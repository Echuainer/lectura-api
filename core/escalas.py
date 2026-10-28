"""Carga de marcos de referencia de velocidad y fluidez lectora, y clasificación por PCPM/PPM."""
import json
from pathlib import Path

RUTA_DEFECTO = Path(__file__).resolve().parent.parent / "config" / "escalas.json"


def cargar_escalas(ruta: str | None = None) -> dict:
    with open(ruta or RUTA_DEFECTO, encoding="utf-8") as f:
        return json.load(f)


def clasificar(pcpm: float, nivel: int, marco: dict) -> str | None:
    # Las escalas van de mayor a menor mínimo: gana el primer tramo que se cumple.
    for nombre, minimo in marco["niveles"].get(str(nivel), []):
        if pcpm >= minimo:
            return nombre
    return None


def rango_velocidad(categoria: str | None, nivel: int, marco: dict) -> str | None:
    orden = [nombre for nombre, _ in marco["niveles"].get(str(nivel), [])]
    if categoria not in orden or marco["adecuado_desde"] not in orden:
        return None
    # La lista va de mayor a menor: lo adecuado está en la misma posición o antes.
    adecuado = orden.index(categoria) <= orden.index(marco["adecuado_desde"])
    return "Adecuado" if adecuado else "Bajo lo esperado"


def rango_fluidez(fluidez: int | None, nivel: int, marco: dict) -> str | None:
    minima = (marco.get("fluidez_minima") or {}).get(str(nivel))
    if fluidez is None or minima is None:
        return None
    return "Adecuado" if fluidez >= minima else "Bajo lo esperado"
