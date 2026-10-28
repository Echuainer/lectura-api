import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.analisis import analizar, normalizar, tokenizar_referencia


def leer(palabras, paso=0.5, dur=0.3, pausas=None):
    """Simula salida Whisper: una palabra cada `paso` s; pausas={indice: segundos extra tras esa palabra}."""
    pausas = pausas or {}
    out, t = [], 0.0
    for i, p in enumerate(palabras):
        out.append({"palabra": p, "inicio": round(t, 3), "fin": round(t + dur, 3)})
        t += paso + pausas.get(i, 0.0)
    return out


def tipos(r):
    return [d["tipo"] for d in r["detalle"]]


def test_normalizar():
    assert normalizar("¡Casa!") == "casa"
    assert normalizar("Árbol") == "arbol"
    assert normalizar("niño,") == "niño"
    assert normalizar("pingüino") == "pinguino"
    assert normalizar("—") == ""


def test_tokenizar_fin_frase():
    t = tokenizar_referencia("El perro corre. Luego, — salta!")
    assert [x["norm"] for x in t] == ["el", "perro", "corre", "luego", "salta"]
    assert [x["fin_frase"] for x in t] == [False, False, True, True, True]


def test_lectura_perfecta():
    r = analizar("El perro corre en el parque.", leer("el perro corre en el parque".split()))
    assert set(tipos(r)) == {"correcta"}
    assert r["correctas"] == 6 and r["errores"] == 0
    assert r["precision_pct"] == 100.0 and r["texto_completo"] is True


def test_sustitucion():
    r = analizar("La casa es grande", leer("la caza es grande".split()))
    assert r["sustituciones"] == 1 and r["correctas"] == 3
    s = [d for d in r["detalle"] if d["tipo"] == "sustitucion"][0]
    assert s["ref"] == "casa" and s["leido"] == "caza"
    assert r["precision_pct"] == 75.0


def test_omision():
    r = analizar("El gato negro duerme mucho", leer("el gato duerme mucho".split()))
    assert r["omisiones"] == 1 and r["errores"] == 1 and r["no_leidas"] == 0


def test_insercion():
    r = analizar("El sol brilla hoy", leer("el sol muy brilla hoy".split()))
    assert r["inserciones"] == 1 and r["errores"] == 0 and r["correctas"] == 4


def test_repeticion():
    r = analizar("La casa es grande", leer("la la casa es grande".split()))
    assert r["repeticiones"] == 1 and r["inserciones"] == 0 and r["correctas"] == 4


def test_autocorreccion():
    r = analizar("La mariposa vuela", leer("la mari mariposa vuela".split()))
    assert r["autocorrecciones"] == 1 and r["correctas"] == 3 and r["errores"] == 0


def test_texto_incompleto():
    r = analizar("Uno dos tres cuatro cinco seis", leer("uno dos tres".split()))
    assert r["no_leidas"] == 3 and r["omisiones"] == 0
    assert r["precision_pct"] == 100.0 and r["texto_completo"] is False


def test_pausas():
    # pausa de 1.0 s extra tras "perro" (intra-frase) y tras "corre." (fin de frase)
    r = analizar("El perro corre. Luego salta", leer("el perro corre luego salta".split(), pausas={1: 1.0, 2: 1.0}))
    assert r["pausas_largas"] == 2 and r["pausas_inesperadas"] == 1
    perro = [d for d in r["detalle"] if d["ref"] == "perro"][0]
    assert perro["pausa_despues"] is not None and perro["pausa_despues"] >= 0.8


def test_pcpm_menos_de_un_minuto():
    # 61 palabras, una cada 0.5 s -> tiempo 30.3 s
    palabras = ["casa"] * 61
    r = analizar(" ".join(palabras), leer(palabras))
    assert r["tiempo_lectura_s"] == 30.3
    assert abs(r["pcpm"] - round(61 / (30.3 / 60), 1)) < 0.05


def test_pcpm_ventana_un_minuto():
    # 180 palabras en ~90 s: dentro del primer minuto entran las de inicio <= 60.0 -> 121
    palabras = [f"p{i}" for i in range(180)]
    r = analizar(" ".join(palabras), leer(palabras))
    assert r["pcpm"] == 121.0
    assert r["ppm"] == round(180 / (r["tiempo_lectura_s"] / 60), 1)


def test_sin_audio():
    r = analizar("Hola mundo", [])
    assert r["pcpm"] == 0 and r["ppm"] == 0 and r["no_leidas"] == 2


# ---------- v4: comparación fonética y reparación de segmentación ----------
from core.analisis import fonetico, recalcular


def test_fonetico():
    assert fonetico("vapor") == fonetico("bapor")
    assert fonetico("hacia") == fonetico("asia")
    assert fonetico("lluvia") == fonetico("yubia")
    assert fonetico("valores") != fonetico("valles")
    assert fonetico("hacia") != fonetico("hasta")
    assert fonetico("cordillera") != fonetico("gordillera")


def test_fonetica_tolera_ortografia_no_errores():
    r = analizar("El vapor sube hacia el cielo", leer("el bapor sube asia el sielo".split()), fonetica=True)
    assert r["errores"] == 0 and r["correctas"] == 6
    r = analizar("sobre los valles", leer("sobre los valores".split()), fonetica=True)
    assert r["sustituciones"] == 1


def test_fonetica_falsa_mantiene_comportamiento():
    r = analizar("El vapor sube", leer("el bapor sube".split()))
    assert r["sustituciones"] == 1 and r["revisar"] == 0


def test_reparar_palabras_pegadas_y_separadas():
    r = analizar("como lluvia. En las cumbres", leer("como lluviaen las cumbres".split()), fonetica=True)
    assert r["errores"] == 0 and r["correctas"] == 5 and r["inserciones"] == 0
    r = analizar("el vapor alcanza zonas", leer("el va por alcanza zonas".split()), fonetica=True)
    assert r["errores"] == 0 and r["inserciones"] == 0
    # "por" existe en el texto: no debe unirse con la palabra anterior
    r = analizar("vapor por eso", leer("vapor por eso".split()), fonetica=True)
    assert r["correctas"] == 3
    # corte en tres con letra suelta al medio
    r = analizar("como nieve. Durante la", leer("como nieveldurante la".split()), fonetica=True)
    assert r["errores"] == 0 and r["correctas"] == 4


def test_detalle_tiene_fin():
    r = analizar("La casa", leer(["la", "casa"]))
    assert all("fin" in d for d in r["detalle"])


def test_recalcular_revisar_cuenta_como_correcta():
    r = analizar("La casa es grande", leer("la caza es grande".split()))
    sust = [d for d in r["detalle"] if d["tipo"] == "sustitucion"][0]
    sust["tipo"] = "revisar"
    r2 = recalcular(r)
    assert r2["revisar"] == 1 and r2["sustituciones"] == 0 and r2["errores"] == 0
    assert r2["precision_pct"] == 100.0 and r2["pcpm"] > r["pcpm"]


# ---------- v4.1: repetición de frase ----------
def test_repeticion_de_frase_falso_inicio():
    r = analizar("nieve. Durante la primavera la nieve",
                 leer("nieve durante la primera durante la primavera la nieve".split()), fonetica=True)
    assert r["repeticiones"] == 1 and r["inserciones"] == 0 and r["autocorrecciones"] == 0
    assert r["correctas"] == 6 and r["errores"] == 0
    grupo = [d for d in r["detalle"] if d["ref"] is None]
    assert len(grupo) == 3 and len({d["grupo"] for d in grupo}) == 1


def test_repeticion_de_frase_relectura():
    r = analizar("donde se limpia para que", leer("donde se limpia parte de se limpia para que".split()), fonetica=True)
    assert r["repeticiones"] == 1 and r["inserciones"] == 0 and r["correctas"] == 5


def test_insercion_suelta_no_se_agrupa():
    r = analizar("El sol brilla hoy", leer("el sol muy brilla hoy".split()))
    assert r["inserciones"] == 1 and r["repeticiones"] == 0


def test_recalcular_cuenta_grupos():
    r = analizar("nieve. Durante la primavera", leer("nieve durante la primera durante la primavera".split()), fonetica=True)
    assert recalcular(r)["repeticiones"] == 1
