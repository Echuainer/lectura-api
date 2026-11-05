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


def test_astoreca_cubre_1ro_con_cortes_mineduc_y_adecuado_desde_media_baja():
    a = cargar_escalas()["marcos"]["astoreca"]
    assert clasificar(29, 1, a) == "Media baja"
    assert clasificar(21, 1, a) == "Muy lenta"
    assert rango_velocidad("Media baja", 1, a) == "Adecuado"   # en 1° basta Media baja
    assert rango_velocidad("Lenta", 1, a) == "Bajo lo esperado"
    assert rango_velocidad("Media baja", 2, a) == "Bajo lo esperado"  # el resto de los niveles no cambia
    # fluidez 1-based: 3 = palabra a palabra es el mínimo de 1°
    assert rango_fluidez(3, 1, a) == "Adecuado"
    assert rango_fluidez(2, 1, a) == "Bajo lo esperado"


def test_convertir_fluidez_entre_marcos():
    from core.escalas import convertir_fluidez
    assert convertir_fluidez(1, "mineduc", "astoreca") == 3   # palabra a palabra
    assert convertir_fluidez(4, "mineduc", "astoreca") == 5   # fluidez
    assert convertir_fluidez(5, "astoreca", "mineduc") == 4
    assert convertir_fluidez(2, "astoreca", "astoreca") == 2  # mismo marco: sin cambio
    assert convertir_fluidez(None, "mineduc", "astoreca") is None
