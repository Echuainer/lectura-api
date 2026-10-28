"""Assessment flow: create (with audio upload URL) → analyze (background job) → review (autosave) → complete."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import assessments as service
from app import repository, storage
from app.deps import assessment_or_404, bad_request, get_conn
from app.security import DIRECTIVO, AuthContext, staff

router = APIRouter(prefix="/api/lectura")


def _can_edit(ctx: AuthContext, a: dict) -> None:
    if ctx.role_id != DIRECTIVO and a["evaluator_user_id"] != ctx.user_id:
        raise HTTPException(403, "Solo quien hizo la evaluación (o un directivo) puede modificarla")


def _view(conn, a: dict) -> dict:
    return service.view(a, repository.latest_job(conn, a["id"], "analyze"))


class AssessmentIn(BaseModel):
    studentId: int
    textId: int
    period: str | None = None
    evaluatorName: str | None = None
    framework: str | None = None
    audioMime: str


class AssessmentPatch(BaseModel):
    model_config = {"extra": "forbid"}
    framework: str | None = None
    expression: int | None = None
    wcpmAdjusted: float | None = None
    observation: str | None = None
    evaluatorName: str | None = None
    period: str | None = None
    rasinski: list[int | None] | None = None
    rasinski2: list[int | None] | None = None


class WordDecision(BaseModel):
    correct: bool


class CompleteIn(BaseModel):
    generateReport: bool = False


@router.get("/assessments")
def list_assessments(courseId: int | None = None, studentId: int | None = None, period: str | None = None,
                     ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    """Complete assessments (the ones that count in reports)."""
    rows = repository.list_assessments(conn, ctx.institution_id, course_id=courseId, student_id=studentId,
                                       period=period)
    return [service.summary(a) for a in rows]


@router.get("/assessments/drafts")
def drafts(ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    """Unfinished assessments of the current user ("Evaluaciones sin terminar")."""
    rows = repository.list_assessments(conn, ctx.institution_id, status="draft", evaluator_user_id=ctx.user_id)
    return [service.summary(a) for a in rows]


@router.post("/assessments", status_code=201)
def create(body: AssessmentIn, ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    """Creates the draft and returns a presigned URL. The browser PUTs the audio there (with the same
    Content-Type) and then calls /analyze."""
    if storage.extension(body.audioMime) is None:
        raise HTTPException(400, "Formato de audio no soportado")
    student = repository.get_student(conn, ctx.institution_id, body.studentId)
    if student is None:
        raise HTTPException(404, "Estudiante no encontrado")
    course = repository.get_course(conn, ctx.institution_id, student["courseId"]) if student["courseId"] else None
    if course is None or course["level"] is None:
        raise HTTPException(400, "El curso del estudiante no es de 1° a 8° básico")
    if repository.get_text(conn, ctx.institution_id, body.textId) is None:
        raise HTTPException(404, "Texto no encontrado")
    mime = body.audioMime.split(";")[0].strip().lower()
    key = storage.new_key(ctx.institution_id, mime)
    assessment_id = repository.create_assessment(
        conn, institution_id=ctx.institution_id, student_id=student["id"], course_id=course["id"],
        text_id=body.textId, evaluator_user_id=ctx.user_id, course_name=course["name"], level=course["level"],
        period=(body.period or "").strip() or None, evaluator_name=(body.evaluatorName or "").strip() or None,
        framework=service.framework_key(body.framework), audio_key=key, audio_mime=mime, status="draft")
    a = repository.get_assessment(conn, ctx.institution_id, assessment_id)
    return {"assessment": service.view(a, with_audio_url=False), "uploadUrl": storage.upload_url(key, mime),
            "uploadHeaders": {"Content-Type": mime}}


@router.post("/assessments/{assessment_id}/analyze", status_code=202)
def analyze(assessment_id: int, ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    a = assessment_or_404(conn, ctx.institution_id, assessment_id)
    _can_edit(ctx, a)
    if a["status"] != "draft":
        raise HTTPException(409, "La evaluación ya está guardada")
    job = repository.active_job(conn, assessment_id, "analyze")
    if job is None:
        if not a["audio_key"] or not storage.exists(a["audio_key"]):
            raise HTTPException(400, "El audio aún no se subió")
        job = repository.get_job(conn, ctx.institution_id, repository.create_job(conn, assessment_id, "analyze"))
    return {"id": job["id"], "kind": job["kind"], "status": job["status"], "error": job["error"]}


@router.get("/jobs/{job_id}")
def job(job_id: int, ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    j = repository.get_job(conn, ctx.institution_id, job_id)
    if j is None:
        raise HTTPException(404, "Trabajo no encontrado")
    return {"id": j["id"], "assessmentId": j["assessment_id"], "kind": j["kind"], "status": j["status"],
            "error": j["error"]}


@router.get("/assessments/{assessment_id}")
def get(assessment_id: int, ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    return _view(conn, assessment_or_404(conn, ctx.institution_id, assessment_id))


@router.patch("/assessments/{assessment_id}")
def patch(assessment_id: int, body: AssessmentPatch, ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    """Autosave of the teacher review. Only the fields sent are changed."""
    a = assessment_or_404(conn, ctx.institution_id, assessment_id)
    _can_edit(ctx, a)
    try:
        fields = service.edit_fields(a, body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise bad_request(e)
    repository.update_assessment(conn, assessment_id, **fields)
    return _view(conn, repository.get_assessment(conn, ctx.institution_id, assessment_id))


@router.post("/assessments/{assessment_id}/words/{index}")
def decide_word(assessment_id: int, index: int, body: WordDecision, ctx: AuthContext = Depends(staff),
                conn=Depends(get_conn)):
    """Teacher decision on a doubtful word ("Leída bien" / "Es error"); WCPM and accuracy are recalculated."""
    a = assessment_or_404(conn, ctx.institution_id, assessment_id)
    _can_edit(ctx, a)
    try:
        fields = service.confirm_word(a, index, body.correct)
    except ValueError as e:
        raise bad_request(e)
    repository.update_assessment(conn, assessment_id, **fields)
    return _view(conn, repository.get_assessment(conn, ctx.institution_id, assessment_id))


@router.post("/assessments/{assessment_id}/complete")
def complete(assessment_id: int, body: CompleteIn, ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    """Marks the assessment as complete (it enters the reports) and queues the hidden study model.
    The AI report is optional; if it fails the assessment is still saved and `reportError` says why."""
    a = assessment_or_404(conn, ctx.institution_id, assessment_id)
    _can_edit(ctx, a)
    if a["result"] is None:
        raise HTTPException(400, "La evaluación aún no tiene análisis")
    if a["expression"] is None:
        raise HTTPException(400, "Elija la categoría de fluidez antes de guardar")
    repository.update_assessment(conn, assessment_id, status="complete")
    if repository.active_job(conn, assessment_id, "prosody") is None:
        repository.create_job(conn, assessment_id, "prosody")
    report_error = None
    if body.generateReport:
        try:
            repository.update_assessment(conn, assessment_id, report=service.student_report(a))
        except Exception as e:
            report_error = f"El informe con IA falló: {e}"
    return _view(conn, repository.get_assessment(conn, ctx.institution_id, assessment_id)) | {
        "reportError": report_error}


@router.delete("/assessments/{assessment_id}", status_code=204)
def discard(assessment_id: int, ctx: AuthContext = Depends(staff), conn=Depends(get_conn)):
    """Discards an unfinished assessment and its audio."""
    a = assessment_or_404(conn, ctx.institution_id, assessment_id)
    _can_edit(ctx, a)
    if a["status"] != "draft":
        raise HTTPException(409, "Solo se pueden descartar evaluaciones sin terminar")
    if (repository.active_job(conn, assessment_id, "analyze") or {}).get("status") == "running":
        raise HTTPException(409, "El audio se está analizando; espere a que termine")
    repository.delete_assessment(conn, assessment_id)
    if a["audio_key"]:
        try:
            storage.delete(a["audio_key"])
        except Exception:
            pass  # the row is gone; an orphan object is cleaned up later (README, "Pendientes")
