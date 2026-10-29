import json
import types
from datetime import datetime

import jwt
import pytest

from sqlalchemy import update

from app import db, repository, security, worker
from conftest import make_client, token
from core import analisis

TEXTO = "La casa es grande. El perro corre rápido por el parque."


def _palabras(leidas):
    return [{"palabra": w, "inicio": i * 0.5, "fin": i * 0.5 + 0.4, "prob": 0.9} for i, w in enumerate(leidas)]


def fake_engine(path, text):
    """Reads "grande" as "grane" and leaves "rápido" as doubtful, like the guided engine would."""
    r = analisis.analizar(text, _palabras("la casa es grane el perro corre rápido por el parque".split()))
    i = next(k for k, it in enumerate(r["detalle"]) if it["ref"] and it["ref"].startswith("rápido"))
    r["detalle"][i]["tipo"] = "revisar"
    r = analisis.recalcular(r)
    r["texto"] = "la casa es grane el perro corre rápido por el parque"
    return r, r["texto"]


@pytest.fixture
def engine_ok(monkeypatch):
    monkeypatch.setattr(worker, "analyze_audio", fake_engine)
    fake = types.SimpleNamespace(VERSION="v-test", evaluar=lambda path, detalle: {
        "version": "v-test", "puntajes": [3, 3, 2, 4], "medidas": {}, "calidad": {"snr_db": 20.0}})
    monkeypatch.setattr(worker, "_prosodia", lambda: fake)
    monkeypatch.setattr("core.informes.informe_alumno", lambda datos: f"Informe nivel {datos['nivel']}")
    monkeypatch.setattr("core.informes.informe_curso", lambda curso, resumen: f"Síntesis {curso}: {resumen['n_evaluados']}")
    return fake


def _text(client, level=5, content=TEXTO, title="El parque"):
    r = client.post("/api/lectura/texts", json={"title": title, "level": level, "content": content})
    assert r.status_code == 201, r.text
    return r.json()


def _assess(client, fake_storage, student_id=1000, period="2026-10", run=True):
    text = _text(client)
    r = client.post("/api/lectura/assessments", json={
        "studentId": student_id, "textId": text["id"], "period": period, "evaluatorName": "Prof. Rojas",
        "framework": "astoreca", "audioMime": "audio/webm;codecs=opus"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["uploadHeaders"] == {"Content-Type": "audio/webm"}
    a = body["assessment"]
    key = body["uploadUrl"].split("/put/")[1]
    fake_storage.objects.add(key)
    job = client.post(f"/api/lectura/assessments/{a['id']}/analyze")
    assert job.status_code == 202, job.text
    if run:
        worker.run_pending()
        assert client.get(f"/api/lectura/jobs/{job.json()['id']}").json()["status"] in ("done", "error")
    return a["id"], job.json()["id"]


# --- Auth --------------------------------------------------------------------------------------

def test_requires_session(engine, fake_storage):
    assert make_client().get("/api/lectura/courses").status_code == 401


@pytest.mark.parametrize("claims", [
    {"aud": "otra-app"}, {"iss": "otro"}, {"mustChangePassword": True}, {"enabled": False}, {"exp": 1}])
def test_rejects_invalid_tokens(engine, fake_storage, claims):
    assert make_client(token(**claims)).get("/api/lectura/courses").status_code == 401


@pytest.mark.parametrize("algorithm", ["HS256", "HS384", "HS512"])
def test_accepts_hmac_algorithms_of_jjwt(engine, fake_storage, algorithm):
    # api-colegio-smart signs with HS512 when JWT_SECRET is 64+ bytes long
    assert make_client(token(algorithm=algorithm)).get("/api/lectura/courses").status_code == 200


def test_rejects_unsigned_token(engine, fake_storage):
    unsigned = jwt.encode(jwt.decode(token(), options={"verify_signature": False}), None, algorithm="none")
    assert make_client(unsigned).get("/api/lectura/courses").status_code == 401


def test_rejects_token_from_before_password_change(engine, fake_storage):
    # user 20 changed the password on 2026-01-01; a token without the stamp or with an older one is stale
    old = token(user_id=20, institution_id=2, passwordChangedAt=1_700_000_000)
    assert make_client(old).get("/api/lectura/courses").status_code == 401
    security.stamp_cache.clear()
    new = token(user_id=20, institution_id=2, passwordChangedAt=1_800_000_000)
    assert make_client(new).get("/api/lectura/courses").status_code == 200


def test_unknown_user_is_rejected(engine, fake_storage):
    assert make_client(token(user_id=999)).get("/api/lectura/courses").status_code == 401


def test_role_guard(engine, fake_storage):
    assert make_client(token(role=security.APODERADO)).get("/api/lectura/courses").status_code == 403
    assert make_client(token(role=security.DOCENTE)).get("/api/lectura/reports/institution").status_code == 403
    assert make_client(token(role=security.DIRECTIVO)).get("/api/lectura/reports/institution").status_code == 200


def test_module_permission_is_required(engine, fake_storage):
    r = make_client(token(permissions={})).get("/api/lectura/courses")
    assert r.status_code == 403 and "plan" in r.json()["detail"]
    assert make_client(token(permissions={"lectura": False})).get("/api/lectura/courses").status_code == 403
    assert make_client(token(permissions={}, platformRole="Admin")).get("/api/lectura/courses").status_code == 200


def test_writes_need_csrf_header(client):
    del client.headers["X-XSRF-TOKEN"]
    r = client.post("/api/lectura/texts", json={"title": "x", "level": 5, "content": "hola"})
    assert r.status_code == 403


def test_safe_request_sets_csrf_cookie(engine, fake_storage):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    c.cookies.set("cs_session", token())
    r = c.get("/api/lectura/courses")
    assert r.status_code == 200 and "XSRF-TOKEN" in r.cookies


# --- Catalog -----------------------------------------------------------------------------------

def test_parse_level():
    assert repository.parse_level("5° Básico") == 5
    assert repository.parse_level("8vo básico") == 8
    assert repository.parse_level("Quinto Básico") == 5
    assert repository.parse_level("1° Medio") is None
    assert repository.parse_level("Kínder") is None
    assert repository.parse_level(None) is None


def test_courses_and_students_are_scoped_to_institution(client):
    courses = client.get("/api/lectura/courses").json()
    assert [(c["id"], c["name"], c["level"], c["studentCount"]) for c in courses] == [
        (100, "5° Básico A", 5, 2), (101, "1° Medio A", None, 1)]
    students = client.get("/api/lectura/courses/100/students").json()
    assert [s["name"] for s in students] == ["Ana Pérez", "Beto Soto"]
    assert client.get("/api/lectura/courses/200/students").status_code == 404  # other institution


def test_texts_crud_and_isolation(client, engine):
    t = _text(client)
    assert t["wordCount"] == 11
    r = client.put(f"/api/lectura/texts/{t['id']}", json={"title": "El parque", "level": 6, "content": "Uno dos tres."})
    assert r.json()["level"] == 6 and r.json()["wordCount"] == 3
    assert client.get("/api/lectura/texts?level=5").json() == []
    assert client.post("/api/lectura/texts", json={"title": " ", "level": 5, "content": "x"}).status_code == 400
    assert client.post("/api/lectura/texts", json={"title": "a", "level": 9, "content": "x"}).status_code == 400
    other = make_client(token(user_id=20, institution_id=2, passwordChangedAt=1_800_000_000))
    assert other.get(f"/api/lectura/texts/{t['id']}").status_code == 404
    assert other.get("/api/lectura/texts").json() == []


def test_config(client):
    c = client.get("/api/lectura/config").json()
    assert c["defaultFramework"] == "astoreca" and "mineduc" in c["frameworks"]
    assert len(c["rasinski"]) == 4 and len(c["rasinski"][0]["levels"]) == 4


# --- Assessment flow ---------------------------------------------------------------------------

def test_full_flow(client, fake_storage, engine_ok):
    assessment_id, job_id = _assess(client, fake_storage)
    assert client.get(f"/api/lectura/jobs/{job_id}").json()["status"] == "done"

    v = client.get(f"/api/lectura/assessments/{assessment_id}").json()
    assert v["status"] == "draft" and v["courseName"] == "5° Básico A" and v["level"] == 5
    assert v["studentName"] == "Ana Pérez" and v["audioUrl"].startswith("https://r2.test/get/reading-audio/1/")
    assert [w["word"] for w in v["doubtfulWords"]] == ["rápido"]
    assert v["errors"] == 1 and v["category"] is not None
    assert "prosody_model" not in v and "prosodyModel" not in v
    assert [d["id"] for d in client.get("/api/lectura/assessments/drafts").json()] == [assessment_id]

    # "Es error": the doubtful word becomes an error and the metrics are recalculated
    index = v["doubtfulWords"][0]["index"]
    v2 = client.post(f"/api/lectura/assessments/{assessment_id}/words/{index}", json={"correct": False}).json()
    assert v2["doubtfulWords"] == [] and v2["errors"] == 2 and v2["accuracyPct"] < v["accuracyPct"]
    assert client.post(f"/api/lectura/assessments/{assessment_id}/words/{index}",
                       json={"correct": True}).status_code == 400  # already decided

    # cannot complete without the fluency category
    assert client.post(f"/api/lectura/assessments/{assessment_id}/complete", json={}).status_code == 400
    v3 = client.patch(f"/api/lectura/assessments/{assessment_id}", json={
        "expression": 4, "wcpmAdjusted": 130, "observation": " Lee bajito ", "rasinski": [3, 3, 2, 4]}).json()
    assert v3["wcpmAdjusted"] == 130 and v3["wcpm"] == 130 and v3["observation"] == "Lee bajito"
    assert v3["category"] == "Media baja" and v3["speedRange"] == "Bajo lo esperado"  # Astoreca 5°: 120–135
    assert v3["fluencyLabel"] == "Lectura unidades cortas" and v3["fluencyRange"] == "Adecuado"
    assert v3["rasinskiTotal"][0] == 12
    assert client.patch(f"/api/lectura/assessments/{assessment_id}", json={"expression": 9}).status_code == 400
    assert client.patch(f"/api/lectura/assessments/{assessment_id}", json={"rasinski": [5, 1, 1, 1]}).status_code == 400
    assert client.patch(f"/api/lectura/assessments/{assessment_id}", json={"unknown": 1}).status_code == 422

    done = client.post(f"/api/lectura/assessments/{assessment_id}/complete", json={"generateReport": True}).json()
    assert done["status"] == "complete" and done["report"] == "Informe nivel 5" and done["reportError"] is None
    assert client.get("/api/lectura/assessments/drafts").json() == []
    assert client.delete(f"/api/lectura/assessments/{assessment_id}").status_code == 409  # only drafts

    # the hidden study model runs in the background and is stored, never shown
    assert worker.run_pending() == 1
    with worker.db.engine.begin() as conn:
        stored = repository.get_assessment(conn, 1, assessment_id)
    assert stored["prosody_model"]["puntajes"] == [3, 3, 2, 4]
    assert "puntajes" not in json.dumps(client.get(f"/api/lectura/assessments/{assessment_id}").json())

    students = client.get("/api/lectura/courses/100/students?period=2026-10").json()
    ana = next(s for s in students if s["id"] == 1000)
    assert ana["assessedInPeriod"] and ana["lastAssessment"]["wcpm"] == 130


def test_analysis_error_is_reported(client, fake_storage, monkeypatch):
    def broken(path, text):
        raise RuntimeError("audio vacío")
    monkeypatch.setattr(worker, "analyze_audio", broken)
    _, job_id = _assess(client, fake_storage)
    job = client.get(f"/api/lectura/jobs/{job_id}").json()
    assert job["status"] == "error" and "audio vacío" in job["error"]


def test_analyze_requires_uploaded_audio(client, fake_storage):
    text = _text(client)
    a = client.post("/api/lectura/assessments", json={"studentId": 1000, "textId": text["id"],
                                                      "audioMime": "audio/webm"}).json()["assessment"]
    assert client.post(f"/api/lectura/assessments/{a['id']}/analyze").status_code == 400


def test_create_validations(client, fake_storage):
    text = _text(client)
    base = {"textId": text["id"], "audioMime": "audio/webm"}
    assert client.post("/api/lectura/assessments", json=base | {"studentId": 2000}).status_code == 404  # other school
    assert client.post("/api/lectura/assessments", json=base | {"studentId": 1002}).status_code == 400  # 1° medio
    assert client.post("/api/lectura/assessments",
                       json=base | {"studentId": 1000, "audioMime": "video/mp4"}).status_code == 400


def test_only_owner_or_director_can_edit(client, fake_storage, engine_ok):
    assessment_id, _ = _assess(client, fake_storage)
    colleague = make_client(token(user_id=11))
    assert colleague.get(f"/api/lectura/assessments/{assessment_id}").status_code == 200
    assert colleague.patch(f"/api/lectura/assessments/{assessment_id}", json={"expression": 3}).status_code == 403
    director = make_client(token(user_id=12, role=security.DIRECTIVO))
    assert director.patch(f"/api/lectura/assessments/{assessment_id}", json={"expression": 3}).status_code == 200


def test_discard_draft_deletes_audio(client, fake_storage, engine_ok):
    assessment_id, _ = _assess(client, fake_storage)
    key = client.get(f"/api/lectura/assessments/{assessment_id}").json()["audioUrl"].split("/get/")[1]
    assert client.delete(f"/api/lectura/assessments/{assessment_id}").status_code == 204
    assert fake_storage.deleted == [key]
    assert client.get(f"/api/lectura/assessments/{assessment_id}").status_code == 404


def test_requeue_and_missing_prosody(client, fake_storage, engine_ok):
    assessment_id, _ = _assess(client, fake_storage)
    client.patch(f"/api/lectura/assessments/{assessment_id}", json={"expression": 4})
    client.post(f"/api/lectura/assessments/{assessment_id}/complete", json={})
    assert worker.enqueue_missing_prosody() == 0  # already queued by /complete
    assert worker.run_pending() == 1
    assert worker.enqueue_missing_prosody() == 0  # current version stored
    engine_ok.VERSION = "v-nueva"
    assert worker.enqueue_missing_prosody() == 1


# --- Reports -----------------------------------------------------------------------------------

def _completed(client, fake_storage, student_id, period, expression=4, wcpm=None):
    assessment_id, _ = _assess(client, fake_storage, student_id=student_id, period=period)
    client.patch(f"/api/lectura/assessments/{assessment_id}", json={
        "expression": expression, "wcpmAdjusted": wcpm, "rasinski": [3, 3, 2, 4]})
    client.post(f"/api/lectura/assessments/{assessment_id}/complete", json={})
    return assessment_id


def test_reports(client, fake_storage, engine_ok):
    first = _completed(client, fake_storage, 1000, "2026-04", wcpm=100)
    with worker.db.engine.begin() as conn:  # same second as the next ones otherwise: dates would tie
        conn.execute(update(db.reading_assessments).where(db.reading_assessments.c.id == first)
                     .values(assessed_at=datetime(2026, 4, 15, 10, 0)))
    _completed(client, fake_storage, 1000, "2026-10", wcpm=140)
    _completed(client, fake_storage, 1001, "2026-10", expression=2, wcpm=90)
    worker.run_pending()

    r = client.get("/api/lectura/reports/courses/100").json()
    assert r["period"] == "2026-10" and r["previousPeriod"] == "2026-04" and r["periods"] == ["2026-10", "2026-04"]
    assert r["kpis"]["evaluated"] == 2 and r["kpis"]["enrolled"] == 2 and r["kpis"]["averageWcpm"] == 115
    assert r["kpis"]["averageDelta"] == 15
    assert [s["name"] for s in r["students"]] == ["Beto Soto", "Ana Pérez"]  # priority: below in both first
    assert r["students"][1]["delta"] == 40
    assert sum(g["n"] for g in r["groups"]) == 2 and len(r["distributions"]) == 2
    assert r["rasinski"]["n"] == 2

    old = client.get("/api/lectura/reports/courses/100?period=2026-04").json()
    assert old["kpis"]["evaluated"] == 1 and old["previousPeriod"] is None

    x = client.get("/api/lectura/reports/courses/100/export")
    assert x.status_code == 200 and x.headers["content-type"].startswith("application/vnd.openxmlformats")

    s = client.post("/api/lectura/reports/courses/100/synthesis?period=2026-10")
    assert s.status_code == 200 and s.text == "Síntesis 5° Básico A: 2"

    t = client.get("/api/lectura/reports/courses/100/texts").json()
    assert len(t["texts"]) == 3 and t["detail"]["kpis"]["readers"] >= 1
    assert any(w["palabra"] == "grande" for w in t["detail"]["words"])

    st = client.get("/api/lectura/reports/students/1000").json()
    assert [h["period"] for h in st["history"]] == ["2026-04", "2026-10"]
    assert [x["label"] for x in st["radar"]["series"]] == ["Primera", "Última"]
    assert client.get("/api/lectura/reports/students/2000").status_code == 404

    director = make_client(token(user_id=12, role=security.DIRECTIVO))
    inst = director.get("/api/lectura/reports/institution").json()
    assert inst["kpis"]["evaluated"] == 2 and inst["kpis"]["enrolled"] == 3
    assert inst["evolution"]["periods"] == ["2026-04", "2026-10"]
    assert [c["courseName"] for c in inst["courses"]] == ["5° Básico A"]
    assert any(a["titulo"] == "Pendientes" for a in inst["alerts"])
    assert director.get("/api/lectura/reports/institution/export").status_code == 200

    # the validation study is internal: platform Admin only
    assert director.get("/api/lectura/reports/study").status_code == 403
    assert director.get("/api/lectura/reports/study/progress.md").status_code == 403
    admin = make_client(token(user_id=12, role=security.DIRECTIVO, platformRole="Admin"))
    study = admin.get("/api/lectura/reports/study").json()
    assert study["pairs"] == 3 and study["metrics"] is None
    md = admin.get("/api/lectura/reports/study/progress.md")
    assert md.status_code == 200 and "Ana" not in md.text
    assert admin.get("/api/lectura/reports/study/final/30.md").status_code == 400


def test_empty_reports(client):
    assert client.get("/api/lectura/reports/courses/100").json()["empty"] is True
    assert client.get("/api/lectura/reports/courses/100/texts").json()["texts"] == []
    assert client.get("/api/lectura/reports/students/1000").json()["empty"] is True
    director = make_client(token(user_id=12, role=security.DIRECTIVO))
    assert director.get("/api/lectura/reports/institution").json()["empty"] is True
