"""Assessment logic moved out of the Streamlit page (app.py of the original app): building the result view,
confirming doubtful words, autosave and completion."""
import copy

from app import repository, storage
from app.worker import ESCALAS, metric_fields
from core import analisis, escalas, informes, referencias

MARCOS = ESCALAS["marcos"]


def framework_key(key: str | None) -> str:
    return key if key in MARCOS else ESCALAS["marco_por_defecto"]


def moment(detalle: list, i: int) -> float:
    """Second of the audio where item i happens (omissions take the end of the previous word)."""
    if detalle[i].get("inicio") is not None:
        return detalle[i]["inicio"]
    return next((x["fin"] for x in reversed(detalle[:i]) if x.get("fin") is not None), 0.0)


def context(detalle: list, i: int) -> str:
    before = [x["ref"] for x in detalle[max(i - 3, 0):i] if x["ref"]]
    after = [x["ref"] for x in detalle[i + 1:i + 4] if x["ref"]]
    return "«…" + " ".join(before + [detalle[i]["ref"] or detalle[i]["leido"]] + after) + "…»"


def effective_wcpm(a: dict) -> float | None:
    return a["wcpm_adjusted"] if a["wcpm_adjusted"] is not None else a["wcpm"]


def _iso(value):
    return value.isoformat() if value is not None else None


def summary(a: dict) -> dict:
    return {
        "id": a["id"], "studentId": a["student_id"], "studentName": a["student_name"], "courseId": a["course_id"],
        "courseName": a["course_name"], "level": a["level"], "textId": a["text_id"], "textTitle": a["text_title"],
        "assessedAt": _iso(a["assessed_at"]), "period": a["period"], "status": a["status"],
        "wcpm": effective_wcpm(a), "category": a["category"], "analyzed": a["result"] is not None,
    }


def view(a: dict, job: dict | None = None, with_audio_url: bool = True) -> dict:
    """Everything the result screen shows. The hidden study model (prosody_model) is never included."""
    key = framework_key(a["framework"])
    marco, level, r = MARCOS[key], a["level"], a["result"]
    wcpm = effective_wcpm(a)
    category = escalas.clasificar(wcpm, level, marco) if wcpm is not None else None
    minimum = dict(marco["niveles"].get(str(level), [])).get(marco["adecuado_desde"])
    fluency_min = (marco.get("fluidez_minima") or {}).get(str(level))
    doubtful = []
    if r:
        doubtful = [{"index": i, "word": it["ref"], "second": moment(r["detalle"], i),
                     "context": context(r["detalle"], i)}
                    for i, it in enumerate(r["detalle"]) if it["tipo"] == "revisar"]
    ht = referencias.percentil_ht(wcpm, level, repository._iso(a["assessed_at"])) if wcpm is not None else None
    others = [m["nombre"] for m in MARCOS.values() if str(level) in m["niveles"]]
    return summary(a) | {
        "framework": key, "evaluatorName": a["evaluator_name"], "evaluatorUserId": a["evaluator_user_id"],
        "transcript": a["transcript"], "result": r, "wcpmDetected": a["wcpm"], "wcpmAdjusted": a["wcpm_adjusted"],
        "accuracyPct": a["accuracy_pct"], "errors": a["errors"], "unexpectedPauses": a["unexpected_pauses"],
        "expression": a["expression"], "observation": a["observation"], "report": a["report"],
        "rasinski": a["rasinski"], "rasinski2": a["rasinski_2"],
        "rasinskiTotal": referencias.interpretar_rasinski(a["rasinski"] or []),
        "category": category,
        "speedRange": escalas.rango_velocidad(category, level, marco),
        "fluencyRange": escalas.rango_fluidez(a["expression"], level, marco),
        "fluencyLabel": marco["fluidez"][a["expression"] - 1] if a["expression"] else None,
        "expectedMinimumWcpm": minimum, "expectedFluency": marco["fluidez"][fluency_min - 1] if fluency_min else None,
        "frameworkCoversLevel": str(level) in marco["niveles"],
        "suggestedFramework": None if str(level) in marco["niveles"] or not others else others[0],
        "doubtfulWords": doubtful,
        "htPercentile": None if not ht else {"band": ht[0], "moment": ht[1], "p50": ht[2]},
        "audioUrl": storage.download_url(a["audio_key"]) if with_audio_url and a["audio_key"] else None,
        "job": None if not job else {"id": job["id"], "kind": job["kind"], "status": job["status"],
                                     "error": job["error"]},
    }


def confirm_word(a: dict, index: int, correct: bool) -> dict:
    """Teacher decision on a doubtful word. Returns the fields to save (result and metrics recalculated)."""
    r = copy.deepcopy(a["result"])
    if not r or not 0 <= index < len(r["detalle"]):
        raise ValueError("Palabra fuera de rango")
    it = r["detalle"][index]
    if it["tipo"] != "revisar":
        raise ValueError("Esa palabra no está por revisar")
    it["tipo"] = "correcta" if correct else ("sustitucion" if it["leido"] else "omision")
    r = analisis.recalcular(r)
    # an adjusted WCPM was typed over the old detected value; once the detected value changes it no longer applies
    return {"result": r, "wcpm_adjusted": None, **metric_fields(r, a["level"], framework_key(a["framework"]))}


def _scores(values, name: str):
    if values is None:
        return None
    if not isinstance(values, list) or len(values) != 4 or any(v is not None and v not in (1, 2, 3, 4) for v in values):
        raise ValueError(f"{name} debe tener 4 puntajes de 1 a 4")
    return values if any(values) else None


def edit_fields(a: dict, changes: dict) -> dict:
    """Autosave of the review form. Only the keys present in `changes` are touched (PATCH)."""
    fields = {}
    if "framework" in changes:
        fields["framework"] = framework_key(changes["framework"])
    marco = MARCOS[fields.get("framework", framework_key(a["framework"]))]
    if "expression" in changes:
        e = changes["expression"]
        if e is not None and not 1 <= int(e) <= len(marco["fluidez"]):
            raise ValueError("Categoría de fluidez fuera de la escala del marco")
        fields["expression"] = e
    if "wcpmAdjusted" in changes:
        v = changes["wcpmAdjusted"]
        if v is not None and v < 0:
            raise ValueError("El PPM ajustado no puede ser negativo")
        fields["wcpm_adjusted"] = None if v is None or v == a["wcpm"] else float(v)
    for key, column in (("observation", "observation"), ("evaluatorName", "evaluator_name"), ("period", "period")):
        if key in changes:
            fields[column] = (changes[key] or "").strip() or None
    if "rasinski" in changes:
        fields["rasinski"] = _scores(changes["rasinski"], "Rasinski")
    if "rasinski2" in changes:
        fields["rasinski_2"] = _scores(changes["rasinski2"], "Rasinski del segundo evaluador")
    if a["result"] is not None:
        wcpm = fields["wcpm_adjusted"] if "wcpm_adjusted" in fields else a["wcpm_adjusted"]
        fields["category"] = escalas.clasificar(a["wcpm"] if wcpm is None else wcpm, a["level"], marco)
    return fields


def student_report(a: dict) -> str:
    """Short AI report. Only figures and word lists go to the API, never the student's name."""
    r, key = a["result"], framework_key(a["framework"])
    data = informes.construir_datos_alumno(a["level"], r, a["category"], a["expression"], r["detalle"], MARCOS[key])
    return informes.informe_alumno(data)
