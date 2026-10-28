"""Report payloads for the Results and Coordination screens. The figures come from core/reportes and
core/estudio (unchanged from the original app); this module only selects the data and shapes the JSON.

Nested objects produced by core/ keep its Spanish keys (categoria, n, pct...), documented in docs/api-reference.md.
"""
import io
import json
import math
from collections import Counter

import numpy as np
import pandas as pd

from app import repository
from app.assessments import MARCOS
from app.worker import ESCALAS
from core import estudio, informes, referencias, reportes

PRECISION_MIN = ESCALAS["precision_minima_pct"]
PRIORITY = {"ninguno": 0, "velocidad": 1, "fluidez": 2, "incompleto": 3, "ambos": 4}
GROUP_ORDER = ("ambos", "velocidad", "fluidez", "ninguno")
PLAN_ORDER = ("ninguno", "velocidad", "fluidez", "ambos")


def clean(value):
    """JSON-safe: numpy scalars to Python, NaN to None."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def _round(x, digits=0):
    if x is None or pd.isna(x):
        return None
    return round(float(x)) if digits == 0 else round(float(x), digits)


def prepared(conn, institution_id: int, **filters) -> pd.DataFrame:
    return reportes.preparar(repository.assessments_frame(conn, institution_id, **filters), MARCOS, PRECISION_MIN)


def _mode(series):
    return series.mode()[0]


def _student_row(f) -> dict:
    return {"assessmentId": int(f["id"]), "studentId": int(f["estudiante_id"]), "name": f["nombre"],
            "courseName": f["curso"], "wcpm": _round(f["pcpm_efectivo"]), "category": f["categoria"],
            "speedRange": f["rango_velocidad"], "fluency": f["fluidez"], "fluencyRange": f["rango_fluidez"],
            "accuracyPct": _round(f["precision_pct"], 1), "delta": _round(f["delta"], 1),
            "toReview": int(f["revisar"]), "group": f["grupo"], "groupLabel": reportes.GRUPOS[f["grupo"]][0],
            "date": f["fecha"], "period": f["periodo"], "textTitle": f["titulo"], "errors": f["errores"]}


def _groups(grupos: dict, total: int) -> list[dict]:
    return [{"key": g, "label": reportes.GRUPOS[g][0], "action": reportes.GRUPOS[g][1],
             "frequency": reportes.GRUPOS[g][2], "n": grupos[g], "pct": round(grupos[g] / max(total, 1) * 100)}
            for g in GROUP_ORDER]


def course_periods(df: pd.DataFrame) -> list[str]:
    return sorted(df["periodo"].dropna().unique(), reverse=True)


def course_report(conn, institution_id: int, course: dict, period: str | None) -> dict:
    """Results · Course · measurement."""
    del_curso = prepared(conn, institution_id, course_id=course["id"])
    periods = course_periods(del_curso) if not del_curso.empty else []
    base = {"course": course, "periods": periods, "period": None}
    if not periods:
        return base | {"empty": True}
    period = period if period in periods else periods[0]
    actual = reportes.ultima_por_estudiante(del_curso[del_curso["periodo"] == period])
    previous = [p for p in periods if p < period]
    anterior = reportes.ultima_por_estudiante(del_curso[del_curso["periodo"] == previous[0]]) if previous else None
    nivel, marco_key = int(_mode(actual["nivel"])), _mode(actual["marco"])
    marco = MARCOS[marco_key]
    enrolled = course["studentCount"]
    grupos = reportes.conteo_grupos(actual)
    avg = round(float(actual["pcpm_efectivo"].mean()))
    prev_avg = round(float(anterior["pcpm_efectivo"].mean())) if anterior is not None else None
    dist = reportes.distribucion(actual, marco, nivel)
    distributions = [{"period": period, "rows": dist}]
    if anterior is not None:
        distributions.append({"period": previous[0], "rows": reportes.distribucion(anterior, marco, nivel)})
    students = actual.assign(_p=actual["grupo"].map(PRIORITY)).sort_values(["_p", "pcpm_efectivo"])
    return clean(base | {
        "empty": False, "period": period, "previousPeriod": previous[0] if previous else None,
        "level": nivel, "framework": marco_key, "frameworkName": marco["nombre"],
        "expectedFrom": marco["adecuado_desde"],
        "kpis": {"evaluated": len(actual), "enrolled": enrolled, "averageWcpm": avg,
                 "averageDelta": None if prev_avg is None else avg - prev_avg,
                 "pctSpeedAdequate": reportes.pct_adecuado(actual["rango_velocidad"]),
                 "pctFluencyAdequate": reportes.pct_adecuado(actual["rango_fluidez"]),
                 "belowInBoth": grupos["ninguno"]},
        "distributions": distributions,
        "groups": _groups(grupos, len(actual)), "incomplete": grupos["incompleto"],
        "rasinski": reportes.resumen_rasinski(actual),
        "students": [_student_row(f) for _, f in students.iterrows()],
        "errors": reportes.errores_frecuentes(actual),
    })


def synthesis_summary(report_df: pd.DataFrame, previous_df: pd.DataFrame | None) -> dict:
    """Aggregated figures for the AI course synthesis (no names)."""
    actual = report_df
    nivel, marco = int(_mode(actual["nivel"])), MARCOS[_mode(actual["marco"])]
    grupos = reportes.conteo_grupos(actual)
    prom = round(float(actual["pcpm_efectivo"].mean()))
    return clean({
        "n_evaluados": len(actual), "nivel": nivel, "marco": marco["nombre"], "pcpm_promedio": prom,
        "pct_velocidad_adecuada": reportes.pct_adecuado(actual["rango_velocidad"]),
        "pct_fluidez_adecuada": reportes.pct_adecuado(actual["rango_fluidez"]),
        "precision_promedio_pct": None if actual["precision_pct"].isna().all() else round(float(actual["precision_pct"].mean()), 1),
        "precision_minima_pct": PRECISION_MIN,
        "n_bajo_precision_minima": int((actual["precision_pct"] < PRECISION_MIN).sum()),
        "por_categoria_fluidez": actual["fluidez"].dropna().value_counts().to_dict(),
        "n_en_riesgo": int(actual["riesgo"].sum()),
        "por_categoria": {x["categoria"]: x["n"] for x in reportes.distribucion(actual, marco, nivel)},
        "pcpm_minimo_por_categoria": dict(marco["niveles"].get(str(nivel), [])),
        "categoria_esperada_desde": marco["adecuado_desde"],
        "grupos_de_apoyo": {reportes.GRUPOS[g][0]: n for g, n in grupos.items()},
        "errores_frecuentes_pct_del_total": {x["tipo"]: x["pct"] for x in reportes.errores_frecuentes(actual)},
        "rasinski": reportes.resumen_rasinski(actual),
        "avance_promedio_ppm": None if previous_df is None else prom - round(float(previous_df["pcpm_efectivo"].mean())),
    })


def course_synthesis(conn, institution_id: int, course: dict, period: str) -> str:
    del_curso = prepared(conn, institution_id, course_id=course["id"])
    if del_curso.empty or period not in set(del_curso["periodo"].dropna()):
        raise ValueError("No hay evaluaciones en esa medición")
    actual = reportes.ultima_por_estudiante(del_curso[del_curso["periodo"] == period])
    previous = [p for p in course_periods(del_curso) if p < period]
    anterior = reportes.ultima_por_estudiante(del_curso[del_curso["periodo"] == previous[0]]) if previous else None
    return informes.informe_curso(course["name"], synthesis_summary(actual, anterior))


def _words(df) -> list[dict]:
    return reportes.palabras_con_error(df)


def course_texts_report(conn, institution_id: int, course: dict, text_id: int | None) -> dict:
    """Results · Course · by text."""
    del_curso = prepared(conn, institution_id, course_id=course["id"])
    if del_curso.empty:
        return {"course": course, "texts": [], "detail": None}
    resumen = reportes.resumen_textos(del_curso)
    texts = [{"textId": int(r.texto_id), "title": r.titulo, "students": int(r.estudiantes), "averageWcpm": r.ppm,
              "averageAccuracyPct": r.precision} for r in resumen.itertuples()]
    ids = [t["textId"] for t in texts]
    text_id = text_id if text_id in ids else (ids[0] if ids else None)
    detail = None
    if text_id is not None:
        ev = del_curso[del_curso["texto_id"] == text_id].sort_values("fecha").groupby("estudiante_id").tail(1)
        nivel, marco_key = int(_mode(ev["nivel"])), _mode(ev["marco"])
        marco = MARCOS[marco_key]
        detail = {
            "textId": text_id, "level": nivel, "framework": marco_key, "expectedFrom": marco["adecuado_desde"],
            "kpis": {"readers": len(ev), "averageWcpm": round(float(ev["pcpm_efectivo"].mean())),
                     "minWcpm": _round(ev["pcpm_efectivo"].min()), "maxWcpm": _round(ev["pcpm_efectivo"].max()),
                     "averageAccuracyPct": None if ev["precision_pct"].isna().all() else round(float(ev["precision_pct"].mean()), 1),
                     "pctSpeedAdequate": reportes.pct_adecuado(ev["rango_velocidad"]),
                     "pctFluencyAdequate": reportes.pct_adecuado(ev["rango_fluidez"])},
            "words": _words(ev), "errors": reportes.errores_frecuentes(ev),
            "distribution": reportes.distribucion(ev, marco, nivel),
            "students": [_student_row(f) for _, f in ev.sort_values("pcpm_efectivo").iterrows()],
        }
    return clean({"course": course, "texts": texts, "detail": detail})


def student_report(conn, institution_id: int, student: dict) -> dict:
    """Results · By student: history, radar, difficult words and AI reports."""
    h = prepared(conn, institution_id, student_id=student["id"])
    if h.empty:
        return {"student": student, "history": [], "empty": True}
    h = h.sort_values("fecha")
    nivel, marco_key = int(h["nivel"].iloc[-1]), h["marco"].iloc[-1]
    marco = MARCOS[marco_key]
    minimum = dict(marco["niveles"].get(str(nivel), [])).get(marco["adecuado_desde"])
    history = []
    for _, f in h.iterrows():
        ht = referencias.percentil_ht(f["pcpm_efectivo"], nivel, f["fecha"])
        ras = referencias.interpretar_rasinski(json.loads(f["rasinski"])) if isinstance(f["rasinski"], str) else None
        history.append(_student_row(f) | {
            "rasinski": None if not ras else {"total": ras[0], "label": ras[1]},
            "htPercentile": None if not ht else {"band": ht[0], "moment": ht[1], "p50": ht[2]},
            "observation": f["observacion"], "report": f["informe"]})
    profile = lambda f: reportes.perfil_radar(f, MARCOS[f["marco"]], PRECISION_MIN)
    radar = [{"label": "Última", "date": h["fecha"].iloc[-1], "values": profile(h.iloc[-1])}]
    if len(h) > 1:
        radar.insert(0, {"label": "Primera", "date": h["fecha"].iloc[0], "values": profile(h.iloc[0])})
    return clean({
        "student": student, "empty": False, "level": nivel, "framework": marco_key,
        "expectedFrom": marco["adecuado_desde"], "expectedMinimumWcpm": minimum,
        "history": history, "radar": {"axes": reportes.EJES_RADAR, "max": reportes.TOPE_RADAR, "series": radar},
        "words": _words(h), "errors": reportes.errores_frecuentes(h), "htSource": referencias.FUENTE_HT,
    })


def institution_report(conn, institution_id: int, period: str | None) -> dict:
    """Coordination: the whole school in one measurement."""
    todos = prepared(conn, institution_id)
    if todos.empty:
        return {"empty": True, "periods": []}
    periods = course_periods(todos)
    period = period if period in periods else periods[0]
    actual = reportes.ultima_por_estudiante(todos[todos["periodo"] == period])
    enrolled = repository.enrolled_by_course(conn, institution_id)
    grupos = reportes.conteo_grupos(actual)
    courses = []
    for curso, g in actual.groupby("curso"):
        nivel, marco_key = int(_mode(g["nivel"])), _mode(g["marco"])
        marco = MARCOS[marco_key]
        courses.append({"courseName": curso, "level": nivel, "framework": marco_key,
                        "distribution": reportes.distribucion(g, marco, nivel),
                        "averageWcpm": round(float(g["pcpm_efectivo"].mean())),
                        "pctSpeedAdequate": reportes.pct_adecuado(g["rango_velocidad"]),
                        "pctFluencyAdequate": reportes.pct_adecuado(g["rango_fluidez"]),
                        "evaluated": len(g), "enrolled": enrolled.get(curso, len(g))})
    evo = reportes.evolucion(todos)
    evolution = {"periods": [str(c) for c in evo.columns],
                 "rows": [{"level": int(n), "values": [_round(v) for v in fila]} for n, fila in evo.iterrows()]}
    return clean({
        "empty": False, "periods": periods, "period": period,
        "kpis": {"evaluated": len(actual), "enrolled": sum(enrolled.values()),
                 "pctSpeedAdequate": reportes.pct_adecuado(actual["rango_velocidad"]),
                 "pctFluencyAdequate": reportes.pct_adecuado(actual["rango_fluidez"]),
                 "intensiveSupport": grupos["ninguno"]},
        "courses": courses, "evolution": evolution, "alerts": reportes.alertas(actual, enrolled),
        "plan": [{"group": reportes.GRUPOS[g][0], "n": grupos[g], "strategy": reportes.GRUPOS[g][1],
                  "frequency": reportes.GRUPOS[g][2]} for g in PLAN_ORDER],
        "students": [_student_row(f) for _, f in actual.iterrows()],
    })


# --- Excel -------------------------------------------------------------------------------------

STUDENT_COLUMNS = {"courseName": "Curso", "name": "Estudiante", "wcpm": "PPM", "category": "Categoría",
                   "speedRange": "Rango velocidad", "fluency": "Fluidez", "fluencyRange": "Rango fluidez",
                   "accuracyPct": "Precisión %", "delta": "Δ PPM", "toReview": "Por revisar", "groupLabel": "Grupo"}


def to_excel(rows: list[dict], columns: dict) -> bytes:
    table = pd.DataFrame([{label: r.get(key) for key, label in columns.items()} for r in rows],
                         columns=list(columns.values()))
    buffer = io.BytesIO()
    table.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


# --- Prosody validation study ------------------------------------------------------------------

def _study_pairs(conn, institution_id: int):
    todas = repository.assessments_frame(conn, institution_id, status=None)
    return todas, estudio.pares(todas)


def study_status(conn, institution_id: int) -> dict:
    todas, pares_ = _study_pairs(conn, institution_id)
    n = len(pares_)
    out = {"pairs": n, "milestones": [{"target": h, "reached": n >= h} for h in estudio.HITOS],
           "byCourse": [{"courseName": c, "readings": k} for c, k in sorted(Counter(p["curso"] for p in pares_).items())],
           "withRasinski": int(todas["rasinski"].notna().sum()) if not todas.empty else 0, "metrics": None}
    if n >= estudio.HITOS[0]:
        hito = max(h for h in estudio.HITOS if n >= h)
        a = estudio.analizar(estudio.muestra_hito(pares_, hito))
        state, text, _ = a["veredicto"]
        out["metrics"] = {"milestone": hito, "byDimension": a["por_dim"],
                          "verdict": {"state": state, "label": estudio.ETIQUETA[state], "text": text}}
    return clean(out)


def study_progress_md(conn, institution_id: int) -> str:
    todas, pares_ = _study_pairs(conn, institution_id)
    return estudio.informe_avance_md(pares_, int(todas["rasinski"].notna().sum()) if not todas.empty else 0)


def study_final_md(conn, institution_id: int, hito: int) -> str:
    _, pares_ = _study_pairs(conn, institution_id)
    if hito not in estudio.HITOS or len(pares_) < hito:
        raise ValueError(f"Se habilita al llegar a {hito} lecturas")
    return estudio.informe_final_md(pares_, hito)


def study_data_xlsx(conn, institution_id: int, hito: int) -> bytes:
    _, pares_ = _study_pairs(conn, institution_id)
    if hito not in estudio.HITOS or len(pares_) < hito:
        raise ValueError(f"Se habilita al llegar a {hito} lecturas")
    buffer = io.BytesIO()
    estudio.tabla_datos(estudio.muestra_hito(pares_, hito)).to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()
