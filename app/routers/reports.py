"""Results (per course, per text, per student), Coordination and the prosody validation study."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from app import reports, repository
from app.deps import MARKDOWN, XLSX, bad_request, course_or_404, download, get_conn
from app.security import AuthContext, admins, directors, staff

router = APIRouter(prefix="/api/lectura/reports")


@router.get("/courses/{course_id}")
def course(course_id: int, period: str | None = None, ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    return reports.course_report(conn, ctx.institution_id, course_or_404(conn, ctx.institution_id, course_id), period)


@router.get("/courses/{course_id}/export")
def course_export(course_id: int, period: str | None = None, ctx: AuthContext = Depends(staff),
                  conn=Depends(get_conn)):
    data = reports.course_report(conn, ctx.institution_id, course_or_404(conn, ctx.institution_id, course_id), period)
    if data.get("empty"):
        raise HTTPException(404, "El curso aún no tiene evaluaciones")
    name = f"resultados_{data['course']['name']}_{data['period']}.xlsx".replace(" ", "_")
    return download(reports.to_excel(data["students"], reports.STUDENT_COLUMNS), name, XLSX)


@router.post("/courses/{course_id}/synthesis", response_class=PlainTextResponse)
def course_synthesis(course_id: int, period: str, ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    """AI synthesis of the course. Only aggregated figures are sent, never names."""
    course_ = course_or_404(conn, ctx.institution_id, course_id)
    try:
        return reports.course_synthesis(conn, ctx.institution_id, course_, period)
    except ValueError as e:
        raise bad_request(e)
    except Exception as e:
        raise HTTPException(502, f"No se pudo generar la síntesis: {e}")


@router.get("/courses/{course_id}/texts")
def course_texts(course_id: int, textId: int | None = None, ctx: AuthContext = Depends(staff),
                 conn=Depends(get_conn)):
    return reports.course_texts_report(conn, ctx.institution_id, course_or_404(conn, ctx.institution_id, course_id),
                                       textId)


@router.get("/students/{student_id}")
def student(student_id: int, ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    s = repository.get_student(conn, ctx.institution_id, student_id)
    if s is None:
        raise HTTPException(404, "Estudiante no encontrado")
    return reports.student_report(conn, ctx.institution_id, s)


@router.get("/institution")
def institution(period: str | None = None, ctx: AuthContext = Depends(directors), conn=Depends(get_conn)):
    return reports.institution_report(conn, ctx.institution_id, period)


@router.get("/institution/export")
def institution_export(period: str | None = None, ctx: AuthContext = Depends(directors), conn=Depends(get_conn)):
    data = reports.institution_report(conn, ctx.institution_id, period)
    if data.get("empty"):
        raise HTTPException(404, "Aún no hay evaluaciones")
    columns = {k: v for k, v in reports.STUDENT_COLUMNS.items() if k not in ("toReview", "groupLabel")}
    return download(reports.to_excel(data["students"], columns), f"coordinacion_{data['period']}.xlsx", XLSX)


@router.get("/study")
def study(ctx: AuthContext = Depends(admins), conn=Depends(get_conn)):
    return reports.study_status(conn, ctx.institution_id)


@router.get("/study/progress.md")
def study_progress(ctx: AuthContext = Depends(admins), conn=Depends(get_conn)):
    return download(reports.study_progress_md(conn, ctx.institution_id).encode(), "estudio_avance.md", MARKDOWN)


@router.get("/study/final/{milestone}.md")
def study_final(milestone: int, ctx: AuthContext = Depends(admins), conn=Depends(get_conn)):
    try:
        text = reports.study_final_md(conn, ctx.institution_id, milestone)
    except ValueError as e:
        raise bad_request(e)
    return download(text.encode(), f"estudio_final_{milestone}.md", MARKDOWN)


@router.get("/study/data/{milestone}.xlsx")
def study_data(milestone: int, ctx: AuthContext = Depends(admins), conn=Depends(get_conn)):
    try:
        content = reports.study_data_xlsx(conn, ctx.institution_id, milestone)
    except ValueError as e:
        raise bad_request(e)
    return download(content, f"estudio_datos_{milestone}.xlsx", XLSX)
