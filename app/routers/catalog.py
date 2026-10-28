"""Configuration, courses and students (read from Colegio Smart), and reading texts."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import repository
from app.deps import bad_request, course_or_404, get_conn
from app.security import AuthContext, current_user, staff
from app.worker import ESCALAS
from core import guiado, referencias

router = APIRouter(prefix="/api/lectura")


@router.get("/me")
def me(ctx: AuthContext = Depends(current_user)):
    return {"userId": ctx.user_id, "email": ctx.email, "institutionId": ctx.institution_id, "roleId": ctx.role_id}


@router.get("/config")
def config(ctx: AuthContext = Depends(staff)):
    """Reading frameworks (config/escalas.json), the Rasinski scale and the voice engine in use."""
    return {"frameworks": ESCALAS["marcos"], "defaultFramework": ESCALAS["marco_por_defecto"],
            "minimumAccuracyPct": ESCALAS["precision_minima_pct"], "levels": list(repository.LEVELS),
            "rasinski": [{"dimension": d, "levels": [{"label": a, "description": b} for a, b in niveles]}
                         for d, niveles in referencias.RASINSKI.items()],
            "engine": guiado.cargar_config()["motor"], "htSource": referencias.FUENTE_HT}


@router.get("/courses")
def courses(ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    return repository.list_courses(conn, ctx.institution_id)


@router.get("/courses/{course_id}/students")
def course_students(course_id: int, period: str | None = None, ctx: AuthContext = Depends(staff),
                    conn=Depends(get_conn)):
    """Students of the course, with their last complete assessment and whether they were assessed in `period`."""
    course_or_404(conn, ctx.institution_id, course_id)
    students = repository.list_students(conn, ctx.institution_id, course_id)
    done = repository.list_assessments(conn, ctx.institution_id, course_id=course_id)
    last = {}
    for a in done:  # newest first
        last.setdefault(a["student_id"], a)
    in_period = {a["student_id"] for a in done if period and a["period"] == period}
    for s in students:
        a = last.get(s["id"])
        s["lastAssessment"] = None if not a else {
            "id": a["id"], "assessedAt": a["assessed_at"].isoformat(), "textTitle": a["text_title"],
            "wcpm": a["wcpm_adjusted"] if a["wcpm_adjusted"] is not None else a["wcpm"]}
        s["assessedInPeriod"] = s["id"] in in_period
    return students


class TextIn(BaseModel):
    title: str
    level: int
    content: str


@router.get("/texts")
def texts(level: int | None = None, ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    return repository.list_texts(conn, ctx.institution_id, level)


@router.get("/texts/{text_id}")
def text(text_id: int, ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    t = repository.get_text(conn, ctx.institution_id, text_id)
    if t is None:
        raise HTTPException(404, "Texto no encontrado")
    return t | {"assessmentCount": repository.count_text_assessments(conn, text_id)}


@router.post("/texts", status_code=201)
def create_text(body: TextIn, ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    try:
        text_id = repository.create_text(conn, ctx.institution_id, ctx.user_id, body.title, body.level, body.content)
    except ValueError as e:
        raise bad_request(e)
    return repository.get_text(conn, ctx.institution_id, text_id)


@router.put("/texts/{text_id}")
def update_text(text_id: int, body: TextIn, ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    try:
        found = repository.update_text(conn, ctx.institution_id, text_id, body.title, body.level, body.content)
    except ValueError as e:
        raise bad_request(e)
    if not found:
        raise HTTPException(404, "Texto no encontrado")
    return repository.get_text(conn, ctx.institution_id, text_id)
