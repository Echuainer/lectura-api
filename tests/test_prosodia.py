import numpy as np
import parselmouth

from core import prosodia as P


def _m(**k):
    base = dict(pct_pausa_en_punto=90, palabras_por_grupo=6, pausas_intra_por_100=2,
                pct_vacilaciones=1, cv_velocidad=0.2, rango_f0_st=9, caida_final_st=-3,
                rango_intensidad_db=16)
    return {**base, **k}


def test_puntuar_cuatros():
    assert P.puntuar(_m()) == [4, 4, 4, 4]


def test_puntuar_escalones():
    s = P.puntuar(_m(pct_pausa_en_punto=70, palabras_por_grupo=4, pausas_intra_por_100=6,
                     pct_vacilaciones=4, cv_velocidad=0.3, rango_f0_st=6, rango_intensidad_db=11))
    assert s == [3, 3, 3, 3]
    s = P.puntuar(_m(pct_pausa_en_punto=None, palabras_por_grupo=3, pausas_intra_por_100=12,
                     pct_vacilaciones=8, cv_velocidad=0.45, rango_f0_st=4, rango_intensidad_db=5))
    assert s == [2, 2, 2, 2]
    s = P.puntuar(_m(palabras_por_grupo=1, pausas_intra_por_100=30, cv_velocidad=0.9,
                     rango_f0_st=1))
    assert s[0] == 1 and s[1] == 1 and s[2] == 1 and s[3] == 1


def test_puntuar_none_y_caida():
    assert P.puntuar(_m(rango_f0_st=None))[0] is None
    assert P.puntuar(_m(palabras_por_grupo=None))[1] is None
    assert P.puntuar(_m(cv_velocidad=None))[3] is None
    assert P.puntuar(_m(caida_final_st=None))[0] == 4
    assert P.puntuar(_m(caida_final_st=0))[0] == 3
    assert P.puntuar({}) == [None] * 4


def _detalle():
    # 12 palabras de 0.3 s; fin de oración +0.5 s, coma +0.3 s, una pausa intra +0.4 s
    refs = ["Hola", "a", "todos,", "hoy", "vamos", "a", "leer.", "El", "gato", "come", "pescado", "fresco."]
    gap = {2: 0.3, 6: 0.5, 8: 0.4}
    out, t = [], 0.0
    for i, r in enumerate(refs):
        out.append({"tipo": "correcta", "ref": r, "leido": r.lower(), "inicio": round(t, 3),
                    "fin": round(t + 0.3, 3), "pausa_despues": None})
        t += 0.3 + gap.get(i, 0.05)
    return out


def test_medidas_tiempo_sin_audio():
    m, cal = P.medidas_desde(None, _detalle())
    assert m["pct_pausa_en_punto"] == 100
    assert m["pct_pausa_en_coma"] == 100
    assert abs(m["pausas_intra_por_100"] - 100 / 12) < 1e-9
    assert abs(m["palabras_por_grupo"] - 12 / 4) < 1e-9
    assert m["pct_vacilaciones"] == 0
    assert m["rango_f0_st"] is None and m["rango_intensidad_db"] is None
    assert cal == {"snr_db": None, "voz_pct": None}


def test_vacios():
    m, _ = P.medidas_desde(None, [])
    assert P.puntuar(m) == [None] * 4


def test_medidas_con_sonido_sintetico():
    d = _detalle()
    sr, T = 16000, d[-1]["fin"] + 0.3
    t = np.arange(int(sr * T)) / sr
    rng = np.random.default_rng(0)
    x = np.zeros_like(t)
    for w in d:
        m = (t >= w["inicio"]) & (t <= w["fin"])
        f = np.linspace(200, 300, m.sum())
        ph = 2 * np.pi * np.cumsum(f) / sr
        x[m] = np.sin(ph) * (0.2 + 0.6 * np.linspace(0, 1, m.sum()) ** 2)
    x += 0.001 * rng.standard_normal(len(x))
    snd = parselmouth.Sound(x, sampling_frequency=sr)
    m, cal = P.medidas_desde(snd, d)
    assert m["rango_f0_st"] > 0
    assert m["rango_intensidad_db"] is not None
    assert cal["snr_db"] is not None and cal["voz_pct"] > 0


def test_evaluar_audio_inexistente():
    r = P.evaluar("no_existe.wav", _detalle())
    assert r["version"] == "v1" and "error" in r
    assert r["puntajes"][0] is None
    assert all(p is not None for p in r["puntajes"][1:])
