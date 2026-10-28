import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import reportes
from core.escalas import cargar_escalas

E = cargar_escalas()
MARCOS = E["marcos"]


def evaluaciones():
    det = lambda tipos: json.dumps({"detalle": [{"tipo": t} for t in tipos], "revisar": tipos.count("revisar")})
    filas = [
        # estudiante, curso, nivel, periodo, fecha, pcpm, ajustado, categoria, expresion, marco, detalle
        (1, "5°A", 5, "2026-07", "2026-07-10", 130, None, "Media baja", 5, "astoreca", det(["sustitucion"])),
        (1, "5°A", 5, "2026-10", "2026-10-10", 140, None, "Media alta", 5, "astoreca", det(["revisar", "repeticion"])),
        (2, "5°A", 5, "2026-10", "2026-10-11", 100, None, "Muy lenta", 3, "astoreca", det(["sustitucion", "omision"])),
        (3, "5°A", 5, "2026-07", "2026-07-11", 125, None, "Media baja", 4, "astoreca", det([])),
        (3, "5°A", 5, "2026-10", "2026-10-12", 118, None, "Lenta", 4, "astoreca", det(["sustitucion"])),
        (4, "6°A", 6, "2026-10", "2026-10-12", 180, 170, "Media alta", None, "astoreca", None),
    ]
    cols = ["estudiante_id", "curso", "nivel", "periodo", "fecha", "pcpm", "pcpm_ajustado", "categoria", "expresion",
            "marco", "resultado_json"]
    df = pd.DataFrame(filas, columns=cols)
    df["precision_pct"] = 98.0
    df["nombre"] = ["A", "A", "B", "C", "C", "D"]
    return reportes.preparar(df, MARCOS, E["precision_minima_pct"])


def test_preparar_grupos_avance_y_revisar():
    df = evaluaciones().set_index(["estudiante_id", "periodo"])
    assert df.loc[(1, "2026-10"), "grupo"] == "ambos"
    assert df.loc[(2, "2026-10"), "grupo"] == "ninguno"
    assert df.loc[(3, "2026-10"), "grupo"] == "velocidad"  # unidades cortas es adecuado en 5°
    assert df.loc[(4, "2026-10"), "grupo"] == "incompleto"
    assert df.loc[(1, "2026-10"), "delta"] == 10 and df.loc[(3, "2026-10"), "delta"] == -7
    assert pd.isna(df.loc[(2, "2026-10"), "delta"])
    assert df.loc[(1, "2026-10"), "revisar"] == 1
    assert df.loc[(4, "2026-10"), "pcpm_efectivo"] == 170


def test_distribucion_y_grupos():
    df = evaluaciones()
    octubre = reportes.ultima_por_estudiante(df[(df["periodo"] == "2026-10") & (df["curso"] == "5°A")])
    dist = reportes.distribucion(octubre, MARCOS["astoreca"], 5)
    assert [d["categoria"] for d in dist][:2] == ["No lector", "Muy lenta"]
    assert {d["categoria"]: d["n"] for d in dist}["Media alta"] == 1
    assert sum(d["n"] for d in dist) == 3
    assert [d["adecuado"] for d in dist] == [False] * 4 + [True] * 3
    assert dist[-1]["rango"] == "168+" and dist[4]["rango"] == "136–149"
    assert reportes.conteo_grupos(octubre) == {"ambos": 1, "velocidad": 1, "fluidez": 0, "ninguno": 1, "incompleto": 0}


def test_errores_frecuentes():
    df = evaluaciones()
    errores = reportes.errores_frecuentes(df[df["periodo"] == "2026-10"])
    assert errores[0] == {"tipo": "Sustituciones", "n": 2, "pct": 50}
    assert {e["tipo"] for e in errores} == {"Sustituciones", "Omisiones", "Repeticiones"}


def test_evolucion_y_alertas():
    df = evaluaciones()
    evo = reportes.evolucion(df)
    assert list(evo.columns) == ["2026-07", "2026-10"]
    assert evo.loc[5, "2026-07"] == 0 and evo.loc[5, "2026-10"] == 33
    octubre = reportes.ultima_por_estudiante(df[df["periodo"] == "2026-10"])
    titulos = [a["titulo"] for a in reportes.alertas(octubre, {"5°A": 4, "6°A": 1})]
    assert "5°A · velocidad" in titulos and "Retrocesos" in titulos and "Pendientes" in titulos


def test_preparar_vacio():
    assert reportes.preparar(pd.DataFrame(), MARCOS, 95).empty


def test_palabras_con_error_y_resumen_textos():
    import json
    import pandas as pd
    from core import reportes
    det = lambda *items: json.dumps({"detalle": [dict(tipo=t, ref=r, leido=l) for t, r, l in items]})
    df = pd.DataFrame({
        "estudiante_id": [1, 2, 2], "texto_id": [7, 7, 8], "titulo": ["A", "A", "B"], "fecha": ["1", "2", "3"],
        "pcpm_efectivo": [100.0, 120.0, 90.0], "precision_pct": [95.0, 97.0, 99.0],
        "resultado_json": [det(("sustitucion", "valles,", "valores"), ("omision", "y", None)),
                           det(("sustitucion", "Valles", "vales"), ("correcta", "sol", "sol")), None],
    })
    p = reportes.palabras_con_error(df)
    assert p[0] == {"palabra": "valles", "errores": 2, "estudiantes": 2, "leido": ["valores", "vales"]}
    assert p[1]["leido"] == ["(omitida)"]
    t = reportes.resumen_textos(df)
    assert list(t["titulo"]) == ["B", "A"] and t.iloc[1]["ppm"] == 110.0 and t.iloc[1]["estudiantes"] == 2


def test_perfil_radar():
    import json
    from core import reportes
    from core.escalas import cargar_escalas
    a = cargar_escalas()["marcos"]["astoreca"]
    fila = {"nivel": 5, "pcpm_efectivo": 136.0, "precision_pct": 97.0, "expresion": 4,
            "resultado_json": json.dumps({"palabras_leidas": 100, "repeticiones": 2, "pausas_inesperadas": 3})}
    p = reportes.perfil_radar(fila, a, 95)
    assert p == {"Velocidad": 100, "Precisión": 102, "Fluidez": 100, "Continuidad": 100}
    fila |= {"pcpm_efectivo": 400.0, "expresion": float("nan"), "resultado_json": None}
    p = reportes.perfil_radar(fila, a, 95)
    assert p["Velocidad"] == 150 and p["Fluidez"] is None and p["Continuidad"] is None


def test_resumen_rasinski():
    import pandas as pd
    from core import reportes
    df = pd.DataFrame({"rasinski": ["[3,3,2,4]", "[2,1,2,3]", None, "[3,null,2,2]"]})
    r = reportes.resumen_rasinski(df)
    assert r["n"] == 2 and r["total_promedio"] == 10.0 and r["pct_buen_progreso"] == 50
    assert r["dimension_mas_baja"] == "Fraseo" and r["por_dimension"]["Ritmo"] == 3.5
    assert reportes.resumen_rasinski(pd.DataFrame({"rasinski": [None]})) is None
