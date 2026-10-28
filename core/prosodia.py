"""Modelo prosódico FIJO y basado en reglas (v1) para lectura oral en español.

Se ejecuta oculto y se compara con la Escala Multidimensional de Fluidez de
Rasinski puntuada por el docente. Las reglas son deterministas y se anclan en
los descriptores de Rasinski y en la literatura de prosodia lectora en español
(pausas en la puntuación, declinación final de F0, rango de F0).

No ajustar con los datos del estudio de validación (contaminaría la comparación)

TABLA DE REGLAS v1 (se evalúa de arriba abajo; la primera que se cumple gana)
  Fraseo (P=pct_pausa_en_punto, G=palabras_por_grupo):
      4: P>=80 y G>=5 | 3: P>=60 y G>=3.5 | 2: G>=2 | 1: resto
      G None -> None; P None -> las condiciones con P son falsas.
  Suavidad (I=pausas_intra_por_100, V=pct_vacilaciones):
      4: I<=3 y V<=2 | 3: I<=8 y V<=5 | 2: I<=15 y V<=10 | 1: resto
  Ritmo (C=cv_velocidad, I=pausas_intra_por_100):
      4: C<=0.25 y I<=5 | 3: C<=0.35 | 2: C<=0.50 | 1: resto
  Expresión y volumen (R=rango_f0_st, D=caida_final_st (puede ser None),
      A=rango_intensidad_db):
      4: R>=8 y (D None o D<=-2) y A>=15 | 3: R>=5 y A>=10 | 2: R>=3 | 1: resto
      R o A None -> None.
"""
import math

import numpy as np

VERSION = "v1"
DIMENSIONES = ["Expresión y volumen", "Fraseo", "Suavidad", "Ritmo"]

PAUSA_S = 0.25            # un hueco >= 0.25 s cuenta como pausa
VENTANA = 5               # palabras por ventana para cv_velocidad
F0_MIN, F0_MAX = 100, 500  # Hz, voces infantiles
MARGEN = 0.05             # s, se descartan los bordes de cada hueco (colas de palabra)
_CIERRE = "\"'»”’)]}"
_FIN_PUNTO, _FIN_COMA = ".?!…", ",;:"


def _fin_ref(ref):
    """Último signo de puntuación de la referencia (ignora comillas/paréntesis de cierre)."""
    return (ref or "").rstrip(_CIERRE)[-1:]


def _pct(v, p):
    return float(np.percentile(v, p))


def _rango(v):
    # Rango robusto 95-5; exige un mínimo de frames para ser confiable.
    return _pct(v, 95) - _pct(v, 5) if len(v) >= 10 else None


def _tiempos(detalle):
    """Palabras habladas ordenadas por inicio, con el hueco hasta la siguiente."""
    h = sorted((d for d in detalle if d.get("inicio") is not None and d.get("fin") is not None),
               key=lambda d: d["inicio"])
    gaps = [round(h[i + 1]["inicio"] - h[i]["fin"], 3) for i in range(len(h) - 1)]
    return h, gaps


def _cv_velocidad(h, gaps):
    # Palabras/segundo por ventana de 5 palabras; el tiempo excluye huecos >= PAUSA_S.
    vel = []
    for i in range(0, len(h) - VENTANA + 1, VENTANA):
        t = sum(w["fin"] - w["inicio"] for w in h[i:i + VENTANA])
        t += sum(g for g in gaps[i:i + VENTANA - 1] if g < PAUSA_S)
        if t > 0:
            vel.append(VENTANA / t)
    if len(vel) < 2 or np.mean(vel) == 0:
        return None
    return float(np.std(vel) / np.mean(vel))


def _prosodia_acustica(snd, h, gaps):
    """(rango_f0_st, caida_final_st, rango_intensidad_db, snr_db, voz_pct)."""
    ini = np.array([w["inicio"] for w in h])
    fin = np.array([w["fin"] for w in h])

    def en_palabra(t):
        return ((t[:, None] >= ini) & (t[:, None] <= fin)).any(axis=1)

    pit = snd.to_pitch(time_step=0.01, pitch_floor=F0_MIN, pitch_ceiling=F0_MAX)
    tp, f0 = pit.xs(), pit.selected_array["frequency"]
    dentro = en_palabra(tp)
    voz = dentro & (f0 > 0)
    voz_pct = 100 * voz.sum() / dentro.sum() if dentro.any() else None
    st = 12 * np.log2(np.where(f0 > 0, f0, 1) / 100.0)
    rango_f0 = _rango(st[voz])

    caidas = []
    for w in h:
        if _fin_ref(w.get("ref")) not in ".!…":
            continue
        m = (tp >= w["inicio"]) & (tp <= w["fin"]) & (f0 > 0)
        mid = (w["inicio"] + w["fin"]) / 2
        a, b = f0[m & (tp < mid)], f0[m & (tp >= mid)]
        if len(a) >= 2 and len(b) >= 2:
            caidas.append(12 * math.log2(np.median(b) / np.median(a)))
    caida = float(np.mean(caidas)) if len(caidas) >= 2 else None

    inten = snd.to_intensity(minimum_pitch=F0_MIN, time_step=0.01)
    ti, db = inten.xs(), inten.values[0]
    ok = np.isfinite(db)
    db_w = db[en_palabra(ti) & ok]
    rango_db = _rango(db_w)
    hueco = np.zeros(len(ti), bool)
    for i, g in enumerate(gaps):
        if g >= PAUSA_S:
            hueco |= (ti > h[i]["fin"] + MARGEN) & (ti < h[i + 1]["inicio"] - MARGEN)
    db_p = db[hueco & ok]
    snr = _pct(db_w, 95) - _pct(db_p, 10) if len(db_w) and len(db_p) else None
    return rango_f0, caida, rango_db, snr, voz_pct


def medidas_desde(sound, detalle):
    """(medidas, calidad). Pura: con sound=None sólo se calculan las medidas de tiempo."""
    h, gaps = _tiempos(detalle or [])
    n = len(h)
    pausa = [g >= PAUSA_S for g in gaps]
    fin_pal = [_fin_ref(w.get("ref")) for w in h[:-1]]

    def pct_pausa(signos):
        idx = [i for i, c in enumerate(fin_pal) if c and c in signos]
        return 100 * sum(pausa[i] for i in idx) / len(idx) if idx else None

    intra = sum(p for p, c in zip(pausa, fin_pal) if not (c and c in _FIN_PUNTO + _FIN_COMA))
    vac = sum(d.get("tipo") in ("repeticion", "autocorreccion", "insercion") for d in detalle or [])
    m = {
        "pct_pausa_en_punto": pct_pausa(_FIN_PUNTO),
        "pct_pausa_en_coma": pct_pausa(_FIN_COMA),
        "pausas_intra_por_100": 100 * intra / n if n else None,
        "palabras_por_grupo": n / (sum(pausa) + 1) if n else None,
        "cv_velocidad": _cv_velocidad(h, gaps),
        "pct_vacilaciones": 100 * vac / n if n else None,
        "rango_f0_st": None, "caida_final_st": None, "rango_intensidad_db": None,
    }
    cal = {"snr_db": None, "voz_pct": None}
    if sound is not None and n:
        r, c, a, snr, voz = _prosodia_acustica(sound, h, gaps)
        m.update(rango_f0_st=r, caida_final_st=c, rango_intensidad_db=a)
        cal = {"snr_db": snr, "voz_pct": voz}
    return m, cal


def puntuar(medidas):
    """4 puntajes 1-4 en orden DIMENSIONES; None si falta una medida necesaria."""
    g = medidas.get
    P, G, I, V, C = (g(k) for k in ("pct_pausa_en_punto", "palabras_por_grupo",
                                    "pausas_intra_por_100", "pct_vacilaciones", "cv_velocidad"))
    R, D, A = g("rango_f0_st"), g("caida_final_st"), g("rango_intensidad_db")

    if R is None or A is None:
        expr = None
    elif R >= 8 and (D is None or D <= -2) and A >= 15:
        expr = 4
    else:
        expr = 3 if R >= 5 and A >= 10 else 2 if R >= 3 else 1

    if G is None:
        fra = None
    else:
        p = P is not None
        fra = 4 if p and P >= 80 and G >= 5 else 3 if p and P >= 60 and G >= 3.5 else 2 if G >= 2 else 1

    if I is None or V is None:
        sua = None
    else:
        sua = 4 if I <= 3 and V <= 2 else 3 if I <= 8 and V <= 5 else 2 if I <= 15 and V <= 10 else 1

    if C is None:
        rit = None
    else:
        rit = 4 if C <= 0.25 and I is not None and I <= 5 else 3 if C <= 0.35 else 2 if C <= 0.50 else 1
    return [expr, fra, sua, rit]


def evaluar(ruta_audio, detalle):
    """Nunca lanza. Si el audio falla, se puntúan igual las dimensiones de tiempo y se informa 'error'."""
    out = {"version": VERSION, "medidas": {}, "puntajes": [None] * 4,
           "calidad": {"snr_db": None, "voz_pct": None}}
    snd = None
    try:
        import parselmouth
        from faster_whisper.audio import decode_audio
        snd = parselmouth.Sound(np.asarray(decode_audio(ruta_audio), dtype=np.float64),
                                sampling_frequency=16000)
    except Exception as e:
        out["error"] = f"audio: {e}"
    try:
        try:
            out["medidas"], out["calidad"] = medidas_desde(snd, detalle)
        except Exception as e:  # fallo acústico: se conservan las medidas de tiempo
            out["error"] = f"acustica: {e}"
            out["medidas"], out["calidad"] = medidas_desde(None, detalle)
        out["puntajes"] = puntuar(out["medidas"])
    except Exception as e:
        out["error"] = f"{out.get('error', '')} {e}".strip()
    return out
