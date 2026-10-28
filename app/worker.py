"""Background jobs: audio analysis and the hidden prosody model of the validation study.

One thread per process takes pending jobs from reading_jobs. The models stay loaded in memory between jobs
(lru_cache in core/guiado and core/transcribir), so the service must run a single process.
"""
import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import and_, select, update

from app import db, repository, storage
from core import analisis, escalas, guiado

log = logging.getLogger("lectura.worker")
ESCALAS = escalas.cargar_escalas()
MAX_ATTEMPTS = 2


def _now():
    return datetime.now(timezone.utc)


def analyze_audio(path: str, text: str) -> tuple[dict, str]:
    """(result, transcript) with the configured engine (config/motor.json)."""
    cfg = guiado.cargar_config()
    if cfg["motor"] == "guiado":
        result = guiado.evaluar(path, text, cfg)
        return result, result["texto"]
    from core import transcribir
    res = transcribir.transcribir(path)
    return analisis.analizar(text, res["palabras"]), res["texto"]


def metric_fields(result: dict, level: int, framework: str | None, wcpm_adjusted=None) -> dict:
    """Columns derived from the result. The category uses the adjusted WCPM when there is one."""
    marco = ESCALAS["marcos"].get(framework or "") or ESCALAS["marcos"][ESCALAS["marco_por_defecto"]]
    wcpm = result["pcpm"] if wcpm_adjusted is None else wcpm_adjusted
    return {"wcpm": result["pcpm"], "wpm": result["ppm"], "accuracy_pct": result["precision_pct"],
            "errors": result["errores"], "unexpected_pauses": result["pausas_inesperadas"],
            "category": escalas.clasificar(wcpm, level, marco)}


def _run_analyze(assessment: dict, folder: str) -> dict:
    path = storage.download(assessment["audio_key"], folder)
    result, transcript = analyze_audio(path, assessment["text_content"])
    return {"result": result, "transcript": transcript, "wcpm_adjusted": None,
            **metric_fields(result, assessment["level"], assessment["framework"])}


def _prosodia():
    from core import prosodia  # deferred: parselmouth is heavy
    return prosodia


def _run_prosody(assessment: dict, folder: str) -> dict | None:
    """Never fails the job for the model itself: core.prosodia.evaluar reports errors inside its output."""
    detalle = (assessment["result"] or {}).get("detalle")
    if not detalle:
        return None
    path = storage.download(assessment["audio_key"], folder)
    return {"prosody_model": _prosodia().evaluar(path, detalle)}


HANDLERS = {"analyze": _run_analyze, "prosody": _run_prosody}


def claim_next(conn) -> dict | None:
    """Takes the oldest pending job. The conditional UPDATE makes the claim atomic across threads or replicas."""
    j = db.reading_jobs
    while True:
        row = conn.execute(select(j).where(j.c.status == "pending").order_by(j.c.id).limit(1)).first()
        if row is None:
            return None
        res = conn.execute(update(j).where(and_(j.c.id == row.id, j.c.status == "pending")).values(
            status="running", started_at=_now(), attempts=row.attempts + 1))
        if res.rowcount:
            return dict(row._mapping) | {"attempts": row.attempts + 1}


def _finish(job_id: int, status: str, error: str | None = None) -> None:
    with db.engine.begin() as conn:
        conn.execute(update(db.reading_jobs).where(db.reading_jobs.c.id == job_id).values(
            status=status, error=error, finished_at=_now()))


def run_job(job: dict) -> None:
    a = db.reading_assessments
    with db.engine.begin() as conn:
        row = conn.execute(repository._assessment_query().where(a.c.id == job["assessment_id"])).first()
    if row is None:
        _finish(job["id"], "error", "La evaluación ya no existe")
        return
    assessment = repository._row(row)
    try:
        with storage.temp_dir() as folder:  # no transaction open while the model runs (it takes seconds)
            fields = HANDLERS[job["kind"]](assessment, folder)
        if fields:
            with db.engine.begin() as conn:
                repository.update_assessment(conn, assessment["id"], **fields)
    except Exception as e:
        log.exception("job %s (%s) failed", job["id"], job["kind"])
        if job["attempts"] < MAX_ATTEMPTS and job["kind"] == "prosody":
            with db.engine.begin() as conn:  # the study model is retried once; the teacher retries analysis by hand
                conn.execute(update(db.reading_jobs).where(db.reading_jobs.c.id == job["id"]).values(status="pending"))
            return
        _finish(job["id"], "error", f"No se pudo analizar el audio: {e}")
        return
    _finish(job["id"], "done")


def run_pending() -> int:
    """Processes every pending job and returns how many it ran (used by the thread and by tests)."""
    n = 0
    while True:
        with db.engine.begin() as conn:
            job = claim_next(conn)
        if job is None:
            return n
        run_job(job)
        n += 1


def requeue_interrupted() -> None:
    """Jobs left running by a restart go back to the queue."""
    with db.engine.begin() as conn:
        conn.execute(update(db.reading_jobs).where(db.reading_jobs.c.status == "running").values(status="pending"))


def enqueue_missing_prosody() -> int:
    """Complete assessments without the current version of the study model (calcular_pendientes in the
    original app). Returns how many jobs it created."""
    try:
        version = _prosodia().VERSION
    except Exception:
        return 0
    a, j = db.reading_assessments, db.reading_jobs
    n = 0
    with db.engine.begin() as conn:
        rows = conn.execute(select(a.c.id, a.c.prosody_model).where(
            and_(a.c.status == "complete", a.c.audio_key.is_not(None), a.c.result.is_not(None)))).all()
        busy = {r[0] for r in conn.execute(select(j.c.assessment_id).where(
            and_(j.c.kind == "prosody", j.c.status.in_(("pending", "running")))))}
        for assessment_id, model in rows:
            if (model or {}).get("version") == version or assessment_id in busy:
                continue
            repository.create_job(conn, assessment_id, "prosody")
            n += 1
    return n


class Worker:
    def __init__(self, poll_seconds: float):
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="lectura-worker", daemon=True)

    def start(self):
        try:
            requeue_interrupted()
            enqueue_missing_prosody()
        except Exception:  # the API must start even if the queue cannot be prepared; the loop retries
            log.exception("could not prepare the job queue")
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=5)

    def _loop(self):
        while not self._stop.is_set():
            try:
                if not run_pending():
                    self._stop.wait(self.poll_seconds)
            except Exception:
                log.exception("worker loop error")
                self._stop.wait(5)
