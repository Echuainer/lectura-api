import json
import sys
import types
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core
from core import estudio, referencias

DIMS = list(referencias.RASINSKI)


def _par(codigo, fecha, humano, modelo=(1, 1, 1, 1), humano2=None, snr=20.0):
    return {"codigo": codigo, "curso": "5°A", "nivel": 5, "fecha": fecha, "texto_id": 1, "humano": list(humano),
            "humano2": list(humano2) if humano2 else None, "modelo": list(modelo),
            "medidas": {"pct_pausa_en_punto": 33.3, "cv_velocidad": 0.42}, "calidad": {"snr_db": snr, "voz_pct": 90.0},
            "version": "v1"}


def _fake_prosodia(monkeypatch, evaluar=None, version="v1"):
    salida = {"version": "v1", "medidas": {"pct_pausa_en_punto": 10.0}, "puntajes": [3, None, 2, 4],
              "calidad": {"snr_db": 20.0, "voz_pct": 90.0}}
    fake = types.SimpleNamespace(VERSION=version, evaluar=evaluar or (lambda ruta, detalle: dict(salida)))
    monkeypatch.setitem(sys.modules, "core.prosodia", fake)
    monkeypatch.setattr(core, "prosodia", fake, raising=False)


def test_kappa_acuerdo_perfecto_es_uno():
    assert estudio.kappa_ponderado([1, 2, 3, 4], [1, 2, 3, 4]) == 1.0


def test_kappa_ejemplo_a_mano():
    # Un solo desacuerdo de un paso (4 vs 3): peso (1/3)^2 = 1/9. Esperado: 32/9 / 4 = 8/9. kappa = 1 - (1/9)/(8/9) = 0,875.
    assert estudio.kappa_ponderado([1, 2, 3, 4], [1, 2, 3, 3]) == pytest.approx(0.875)


def test_kappa_none_sin_variacion_o_pocos_pares():
    assert estudio.kappa_ponderado([2, 2, 2], [2, 2, 2]) is None
    assert estudio.kappa_ponderado([1], [1]) is None


def test_metricas_acuerdo_y_matriz():
    pares = [_par(f"E{i}", "2026-10-01", [h, 1, 1, 1], [m, None, None, None])
             for i, (h, m) in enumerate([(1, 1), (2, 2), (3, 4), (4, 4), (4, 1)], start=1)]
    m = estudio.metricas(pares, 0)
    assert m["n"] == 5
    assert m["acuerdo_exacto_pct"] == 60.0  # 3 de 5 iguales
    assert m["acuerdo_mas_menos_1_pct"] == 80.0  # 4 de 5 a un punto o menos
    assert m["matriz"][3] == [1, 0, 0, 1]  # humano 4: modelo 1 y modelo 4
    assert m["matriz"][2][3] == 1  # humano 3 vio modelo 4
    assert sum(map(sum, m["matriz"])) == 5


def test_metricas_omite_modelo_sin_puntaje():
    pares = [_par("E1", "2026-10-01", [1, 1, 1, 1], [None, 1, 1, 1]), _par("E2", "2026-10-02", [2, 2, 2, 2], [2, 2, 2, 2])]
    assert estudio.metricas(pares, 0)["n"] == 1


def test_metricas_total_bland_altman():
    pares = [_par("E1", "2026-10-01", [1, 1, 1, 1], [2, 2, 2, 2]),
             _par("E2", "2026-10-02", [2, 2, 2, 2], [3, 3, 3, 3]),
             _par("E3", "2026-10-03", [3, 3, 3, 3], [4, 4, 4, 4]),
             _par("E4", "2026-10-04", [1, 2, 3, 2], [2, 3, 4, 3]),
             _par("E5", "2026-10-05", [1, 1, 1, 1], [None, 1, 1, 1])]  # esta se omite: sin cuatro puntajes del modelo
    t = estudio.metricas_total(pares)
    assert t["n"] == 4
    assert t["r"] == 1.0
    assert t["dif_media"] == 4.0
    assert t["dif_sd"] == 0.0


def test_veredicto_tres_resultados():
    def m(kappa, acuerdo=95.0):
        return {"kappa_ponderado": kappa, "acuerdo_mas_menos_1_pct": acuerdo}
    base = {d: m(0.8) for d in DIMS}
    estado, texto, no = estudio.veredicto(base)
    assert estado == "VALIDO" and no == [] and "0,60" in texto
    estado, texto, no = estudio.veredicto({**base, "Ritmo": m(0.3)})
    assert estado == "NO_VALIDO" and no == ["Ritmo"] and "Ritmo" in texto
    estado, _, no = estudio.veredicto({**base, "Fraseo": m(0.5)})
    assert estado == "UTIL_COMO_SUGERENCIA" and no == []
    estado, _, _ = estudio.veredicto({**base, "Suavidad": m(0.8, acuerdo=85.0)})  # kappa basta, pero ±1 no llega a 90
    assert estado == "UTIL_COMO_SUGERENCIA"


def test_avance_no_muestra_puntajes_del_modelo():
    pares = [_par(f"E{i:04d}", f"2026-10-0{i}", [2, 3, 3, 4], [4, 4, 4, 4], humano2=[2, 2, 3, 4], snr=12.5)
             for i in range(1, 4)]
    texto = estudio.informe_avance_md(pares, 5)
    assert estudio.BLINDAJE in texto
    tabla = "\n".join(linea for linea in texto.splitlines() if linea.startswith("|"))
    assert "modelo" not in tabla.lower()
    assert "pct_pausa" not in texto and "cv_velocidad" not in texto
    assert "E0001" in tabla and "2.º evaluador" in tabla
    assert "3 de 30 (hito 1) / 3 de 100 (hito 2)" in texto


def test_informe_final_usa_las_primeras_treinta_por_fecha():
    # E0001 es la lectura más reciente: el informe de 30 debe dejar fuera E0001 a E0005
    pares = [_par(f"E{k:04d}", (date(2026, 1, 1) + timedelta(days=35 - k)).isoformat(), [1 + k % 4, 2, 3, 4],
                  [1 + k % 4, 2, 3, 4]) for k in range(1, 36)]
    texto = estudio.informe_final_md(pares, 30)
    lineas_datos = [linea for linea in texto.splitlines() if linea.startswith("| E00")]
    assert len(lineas_datos) == 30
    assert "E0006" in texto and "E0035" in texto
    assert "E0001" not in texto and "E0005" not in texto
    assert "Muestra:** 30 de 30" in texto
    assert "## Veredicto" in texto


def test_pares_nunca_incluye_nombres():
    import pandas as pd
    modelo = json.dumps({"version": "v1", "puntajes": [3, 3, 2, 4], "medidas": {}, "calidad": {}})
    base = dict(curso="5°A", nivel=5, fecha="2026-10-01T10:00:00", texto_id=1, estado="completa",
                rasinski="[3,3,2,4]", rasinski_2=None)
    df = pd.DataFrame([dict(base, id=1, nombre="Ana Pérez", prosodia_modelo=modelo),
                       dict(base, id=2, nombre="Beto Soto", prosodia_modelo=None)])  # sin análisis del modelo: no entra
    lista = estudio.pares(df)
    assert len(lista) == 1
    assert lista[0]["codigo"].startswith("E") and lista[0]["codigo"][1:].isdigit()
    serializado = json.dumps(lista, ensure_ascii=False)
    assert "Ana" not in serializado and "Pérez" not in serializado and "Beto" not in serializado
