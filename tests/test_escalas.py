import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.escalas import cargar_escalas, clasificar, rango_fluidez, rango_velocidad


def test_escalas_mineduc():
    m = cargar_escalas()["marcos"]["mineduc"]
    assert clasificar(125, 5, m) == "Media baja"
    assert clasificar(50, 5, m) == "Muy lenta"
    assert clasificar(300, 8, m) == "Muy rápida"
    assert clasificar(140, 7, m) == "Lenta"
    assert clasificar(100, 3, m) == "Rápida"  # 1° a 4° agregados (tabla Educando Juntos)
    assert rango_velocidad("Media baja", 5, m) == "Adecuado"
    assert rango_velocidad("Lenta", 5, m) == "Bajo lo esperado"
    assert rango_fluidez(2, 5, m) is None


def test_escalas_astoreca():
    e = cargar_escalas()
    assert e["marco_por_defecto"] == "astoreca"
    a = e["marcos"]["astoreca"]
    assert clasificar(3, 5, a) == "No lector"
    assert clasificar(6, 5, a) == "Muy lenta"
    assert clasificar(140, 7, a) == "Lenta"
    assert clasificar(161, 8, a) == "Media alta"
    assert clasificar(70, 2, a) == "Media alta"
    assert rango_velocidad("Media alta", 6, a) == "Adecuado"
    assert rango_velocidad("Media baja", 6, a) == "Bajo lo esperado"
    assert rango_velocidad(None, 6, a) is None
    # fluidez 1-based: 4 = unidades cortas
    assert rango_fluidez(4, 5, a) == "Adecuado"
    assert rango_fluidez(4, 6, a) == "Bajo lo esperado"
    assert rango_fluidez(5, 8, a) == "Adecuado"
    assert rango_fluidez(None, 8, a) is None
    assert a["fluidez"][3] == "Lectura unidades cortas"
