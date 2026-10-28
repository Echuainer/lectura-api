"""Verificación guiada con emisiones CTC sintéticas (sin descargar el modelo)."""
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import guiado

LETRAS = "abcdefghijklmnopqrstuvwxyzáéíóúñü"
VOCAB = {"<pad>": 0, "|": 1, **{c: i + 2 for i, c in enumerate(LETRAS)}}
CFG = {"umbral_ok": 1.5, "umbral_error": 3.0, "seg_por_frame": 0.02}


def fila(principal, p=0.9, segundo=None, p2=0.0):
    v = len(VOCAB)
    resto = (1.0 - p - p2) / (v - (2 if segundo else 1))
    row = np.full(v, resto)
    row[VOCAB[principal]] = p
    if segundo:
        row[VOCAB[segundo]] = p2
    return np.log(row)


def emitir(palabras, especiales=None, pausa=2):
    """palabras -> frames: 2 frames por letra, blank entre letras dobles, '|' + blanks entre palabras.
    especiales: {(indice_palabra, indice_letra): (letra, p, segunda, p2)} para frames ambiguos."""
    especiales = especiales or {}
    filas = [fila("<pad>")] * 3
    for w, palabra in enumerate(palabras):
        for i, ch in enumerate(palabra):
            if i and ch == palabra[i - 1]:
                filas.append(fila("<pad>"))
            args = especiales.get((w, i), (ch,))
            filas += [fila(*args)] * 2
        filas += [fila("|")] + [fila("<pad>")] * pausa
    return np.array(filas, dtype=np.float32)


def test_decodificar_ctc():
    pal = guiado.decodificar_ctc(emitir(["casa", "el", "valle"]), VOCAB, 0.02)
    assert [p["palabra"] for p in pal] == ["casa", "el", "valle"]
    assert pal[0]["inicio"] < pal[0]["fin"] < pal[1]["inicio"]


def test_ids_palabra_quita_tildes_desconocidas():
    v = {k: i for k, i in VOCAB.items() if k != "á"}
    assert guiado.ids_palabra("Árbol", v) == [v[c] for c in "arbol"]


def test_puntaje_ctc():
    logp = emitir(["valles"])
    bueno = guiado.puntaje_ctc(logp, guiado.ids_palabra("valles", VOCAB), 0)
    malo = guiado.puntaje_ctc(logp, guiado.ids_palabra("pocas", VOCAB), 0)
    assert bueno > malo
    assert guiado.puntaje_libre(logp) >= bueno
    assert guiado.puntaje_ctc(logp[:3], guiado.ids_palabra("valles", VOCAB), 0) == -math.inf


def test_confusion_del_motor_se_corrige():
    # el motor duda entre g y c: greedy escribe "gordillera", pero "cordillera" calza casi igual
    logp = emitir(["sobre", "la", "cordillera", "alta"], {(2, 0): ("g", 0.5, "c", 0.45)})
    r = guiado.evaluar_logp("sobre la cordillera alta", logp, VOCAB, CFG)
    assert "gordillera" in r["texto"]
    assert r["errores"] == 0 and r["correctas"] == 4


def test_error_real_se_mantiene():
    r = guiado.evaluar_logp("sobre los valles", emitir(["sobre", "los", "valores"]), VOCAB, CFG)
    assert r["sustituciones"] == 1
    s = [d for d in r["detalle"] if d["tipo"] == "sustitucion"][0]
    assert s["margen"] >= CFG["umbral_error"]


def test_omision_real_se_mantiene():
    r = guiado.evaluar_logp("ese vapor invisible y liviano", emitir(["ese", "vapor", "y", "liviano"]), VOCAB, CFG)
    assert r["omisiones"] == 1


def test_zona_intermedia_queda_para_revisar():
    logp = emitir(["sobre", "la", "cordillera", "alta"], {(2, 0): ("g", 0.5, "c", 0.45)})
    r = guiado.evaluar_logp("sobre la cordillera alta", logp, VOCAB, {**CFG, "umbral_ok": -1.0, "umbral_error": 50.0})
    assert r["revisar"] == 1 and r["errores"] == 0


def test_repeticion_detectada_por_decodificacion_libre():
    r = guiado.evaluar_logp("caen a la tierra", emitir(["caen", "caen", "a", "la", "tierra"]), VOCAB, CFG)
    assert r["repeticiones"] == 1 and r["correctas"] == 4


# ---------- v4.1 ----------
def test_grupo_de_sustituciones_mal_segmentado():
    # el motor partió "empuja esas" como "em" + "pujaesas": por separado no se puede verificar, en grupo sí
    logp = emitir(["el", "viento", "em", "pujaesas", "nubes"])
    r = guiado.evaluar_logp("el viento empuja esas nubes", logp, VOCAB, CFG)
    assert r["errores"] == 0 and r["revisar"] == 0 and r["correctas"] == 5


def test_grupo_con_errores_reales_se_mantiene():
    # dos sustituciones reales seguidas: el grupo no calza y cada una sigue siendo error
    logp = emitir(["el", "gato", "bebe", "carne"])
    r = guiado.evaluar_logp("el perro come carne", logp, VOCAB, CFG)
    assert r["sustituciones"] == 2 and r["correctas"] == 2


def test_letra_final_queda_para_revisar():
    logp = emitir(["que", "podamos", "usarlas", "en"])
    r = guiado.evaluar_logp("que podamos usarla en", logp, VOCAB, {**CFG, "umbral_ok": 5.0, "umbral_error": 50.0})
    it = [d for d in r["detalle"] if d["ref"] == "usarla"][0]
    assert it["tipo"] == "revisar" and r["revisar"] == 1


# ---------- v4.2: pronunciación chilena ----------
def test_variantes_letras_debiles():
    v = guiado.variantes("esas")
    assert v[0] == "esas" and "esa" in v and "eas" not in v  # la s ante vocal no es débil
    assert "empua" in guiado.variantes("empuja")
    assert "pesao" in guiado.variantes("pesado") and "verda" in guiado.variantes("verdad")
    assert guiado.variantes("casa") == ["casa"]
    assert len(guiado.variantes("desdes" * 3)) <= 16


def test_s_aspirada_y_j_suave_no_son_error():
    # "empuja esas" dicho a la chilena: j suave y s final aspirada; el motor parte mal las palabras
    logp = emitir(["el", "viento", "em", "puaesa", "nubes"])
    r = guiado.evaluar_logp("el viento empuja esas nubes", logp, VOCAB, CFG)
    # sin variantes queda todo "por revisar"; con variantes calza y no molesta al docente
    assert r["errores"] == 0 and r["revisar"] == 0 and r["correctas"] == 5


def test_letra_debil_no_oculta_error_real():
    r = guiado.evaluar_logp("sobre los valles", emitir(["sobre", "los", "valores"]), VOCAB, CFG)
    assert r["sustituciones"] == 1


# ---------- v4.4: margen por letra ----------
def test_config_por_defecto_calibrada():
    cfg = guiado.cargar_config()
    assert cfg["umbral_ok"] == 1.5 and cfg["umbral_error"] == 3.0


def test_valores_es_error_con_margen_por_letra():
    r = guiado.evaluar_logp("sobre los valles y las", emitir(["sobre", "los", "valores", "y", "las"]), VOCAB, CFG)
    it = [d for d in r["detalle"] if d["ref"] == "valles"][0]
    assert it["tipo"] == "sustitucion" and it["margen"] >= 3.0


def test_ventana_corta_no_confirma_error():
    # el motor dejó muy poco audio para "empuja": la racha queda por revisar, no como error
    logp = emitir(["el", "viento", "en", "pocas", "nubes"], pausa=0)  # habla rápida, como en el audio real
    r = guiado.evaluar_logp("el viento empuja esas nubes", logp, VOCAB, CFG)
    assert r["errores"] == 0 and r["revisar"] == 2


def test_palabra_corta_nunca_es_error():
    r = guiado.evaluar_logp("cuando el vapor sube", emitir(["cuando", "vapor", "sube"]), VOCAB, CFG)
    el = [d for d in r["detalle"] if d["ref"] == "el"][0]
    assert el["tipo"] == "revisar" and r["errores"] == 0
