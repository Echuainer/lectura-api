"""Queries. Courses and students are read from the api-colegio-smart tables; texts and assessments are ours.

`assessments_frame` returns the assessments with the column names that core/ (reportes, estudio) expects
from the original SQLite app, so that code is reused unchanged.
"""
import json
import re
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import and_, delete, func, insert, select, update
from sqlalchemy.engine import Connection

from app import db
from core.analisis import tokenizar_referencia

LEVELS = range(1, 9)
_ORDINALS = {"primer": 1, "primero": 1, "segundo": 2, "tercer": 3, "tercero": 3, "cuarto": 4, "quinto": 5,
             "sexto": 6, "séptimo": 7, "septimo": 7, "octavo": 8}
ASSESSMENT_FIELDS = frozenset({
    "period", "audio_key", "audio_mime", "transcript", "result", "wcpm", "wpm", "accuracy_pct", "errors",
    "unexpected_pauses", "category", "expression", "wcpm_adjusted", "observation", "report", "evaluator_name",
    "framework", "status", "rasinski", "rasinski_2", "prosody_model",
})
STATUS_ES = {"complete": "completa", "draft": "borrador"}


def now():
    return datetime.now(timezone.utc)


def parse_level(level_name: str | None) -> int | None:
    """Basic-education grade (1 to 8) from a Colegio Smart level name: "5° Básico", "5to básico", "Quinto Básico".
    Secondary ("Medio") and pre-school levels return None: the reading frameworks only cover 1° to 8° básico."""
    name = (level_name or "").strip().lower()
    if not name or "medio" in name or "kinder" in name or "kínder" in name:
        return None
    m = re.match(r"\s*(\d+)", name)
    if m:
        n = int(m.group(1))
        return n if n in LEVELS else None
    first = name.split()[0] if name.split() else ""
    return _ORDINALS.get(first)


# --- Courses and students (api-colegio-smart) --------------------------------------------------

def _course_query():
    c, l = db.cs_courses, db.cs_cycle_type_levels
    return select(c.c.id, c.c.letter, l.c.name.label("level_name")).select_from(
        c.outerjoin(l, l.c.id == c.c.cycle_type_level_id))


def _course_dict(row) -> dict:
    name = f"{row.level_name or ''} {row.letter or ''}".strip()  # CourseOptionResponse
    return {"id": row.id, "name": name, "level": parse_level(row.level_name)}


def list_courses(conn: Connection, institution_id: int) -> list[dict]:
    s = db.cs_students
    counts = dict(conn.execute(
        select(s.c.course_id, func.count()).where(s.c.institution_id == institution_id).group_by(s.c.course_id)).all())
    rows = conn.execute(_course_query().where(db.cs_courses.c.institution_id == institution_id)).all()
    courses = [_course_dict(r) | {"studentCount": counts.get(r.id, 0)} for r in rows]
    return sorted(courses, key=lambda x: (x["level"] or 99, x["name"]))


def get_course(conn: Connection, institution_id: int, course_id: int) -> dict | None:
    row = conn.execute(_course_query().where(and_(db.cs_courses.c.id == course_id,
                                                  db.cs_courses.c.institution_id == institution_id))).first()
    return _course_dict(row) if row else None


def _full_name(name, last_name) -> str:
    return " ".join(x.strip() for x in (name, last_name) if x and x.strip())


def list_students(conn: Connection, institution_id: int, course_id: int) -> list[dict]:
    s = db.cs_students
    rows = conn.execute(select(s.c.id, s.c.name, s.c.last_name).where(
        and_(s.c.institution_id == institution_id, s.c.course_id == course_id))).all()
    students = [{"id": r.id, "name": _full_name(r.name, r.last_name), "lastName": r.last_name or ""} for r in rows]
    return sorted(students, key=lambda x: (x["lastName"].lower(), x["name"].lower()))


def get_student(conn: Connection, institution_id: int, student_id: int) -> dict | None:
    s = db.cs_students
    row = conn.execute(select(s.c.id, s.c.name, s.c.last_name, s.c.course_id).where(
        and_(s.c.id == student_id, s.c.institution_id == institution_id))).first()
    if not row:
        return None
    return {"id": row.id, "name": _full_name(row.name, row.last_name), "courseId": row.course_id}


def enrolled_by_course(conn: Connection, institution_id: int) -> dict[str, int]:
    """Students per course name (core.reportes.alertas uses the course name as key)."""
    return {c["name"]: c["studentCount"] for c in list_courses(conn, institution_id)}


# --- Texts -------------------------------------------------------------------------------------

def _text_dict(row) -> dict:
    return {"id": row.id, "title": row.title, "level": row.level, "content": row.content,
            "wordCount": row.word_count, "createdAt": row.created_at.isoformat() if row.created_at else None}


def list_texts(conn: Connection, institution_id: int, level: int | None = None) -> list[dict]:
    t = db.reading_texts
    q = select(t).where(t.c.institution_id == institution_id)
    if level is not None:
        q = q.where(t.c.level == level)
    return [_text_dict(r) for r in conn.execute(q.order_by(t.c.level, t.c.title))]


def get_text(conn: Connection, institution_id: int, text_id: int) -> dict | None:
    t = db.reading_texts
    row = conn.execute(select(t).where(and_(t.c.id == text_id, t.c.institution_id == institution_id))).first()
    return _text_dict(row) if row else None


def _validate_text(title: str, level: int, content: str) -> tuple[str, int, str, int]:
    title, content = (title or "").strip(), (content or "").strip()
    if not title or not content:
        raise ValueError("Título y contenido son obligatorios.")
    if int(level) not in LEVELS:
        raise ValueError("El nivel debe estar entre 1 y 8.")
    words = len(tokenizar_referencia(content))
    if not words:
        raise ValueError("El texto no tiene palabras.")
    return title, int(level), content, words


def create_text(conn: Connection, institution_id: int, user_id: int, title: str, level: int, content: str) -> int:
    title, level, content, words = _validate_text(title, level, content)
    return conn.execute(insert(db.reading_texts).values(
        institution_id=institution_id, title=title, level=level, content=content, word_count=words,
        created_by=user_id, created_at=now(), updated_at=now()).returning(db.reading_texts.c.id)).scalar_one()


def update_text(conn: Connection, institution_id: int, text_id: int, title: str, level: int, content: str) -> bool:
    """Saved assessments keep their result; new ones use the corrected text."""
    title, level, content, words = _validate_text(title, level, content)
    t = db.reading_texts
    res = conn.execute(update(t).where(and_(t.c.id == text_id, t.c.institution_id == institution_id)).values(
        title=title, level=level, content=content, word_count=words, updated_at=now()))
    return res.rowcount > 0


def count_text_assessments(conn: Connection, text_id: int) -> int:
    a = db.reading_assessments
    return conn.execute(select(func.count()).where(a.c.text_id == text_id)).scalar_one()


# --- Assessments -------------------------------------------------------------------------------

def create_assessment(conn: Connection, **values) -> int:
    values.setdefault("assessed_at", now())
    values.update(created_at=now(), updated_at=now())
    return conn.execute(insert(db.reading_assessments).values(**values)
                        .returning(db.reading_assessments.c.id)).scalar_one()


def update_assessment(conn: Connection, assessment_id: int, **fields) -> None:
    unknown = set(fields) - ASSESSMENT_FIELDS
    if unknown:
        raise ValueError(f"Unknown assessment fields: {sorted(unknown)}")
    if fields:
        a = db.reading_assessments
        conn.execute(update(a).where(a.c.id == assessment_id).values(**fields, updated_at=now()))


def delete_assessment(conn: Connection, assessment_id: int) -> None:
    conn.execute(delete(db.reading_assessments).where(db.reading_assessments.c.id == assessment_id))


def _assessment_query():
    a, t, s = db.reading_assessments, db.reading_texts, db.cs_students
    return select(a, t.c.title.label("text_title"), t.c.content.label("text_content"),
                  s.c.name.label("student_first_name"), s.c.last_name.label("student_last_name")).select_from(
        a.join(t, t.c.id == a.c.text_id).outerjoin(s, s.c.id == a.c.student_id))


def get_assessment(conn: Connection, institution_id: int, assessment_id: int) -> dict | None:
    a = db.reading_assessments
    row = conn.execute(_assessment_query().where(
        and_(a.c.id == assessment_id, a.c.institution_id == institution_id))).first()
    return _row(row) if row else None


def _row(row) -> dict:
    d = dict(row._mapping)
    d["student_name"] = _full_name(d.pop("student_first_name"), d.pop("student_last_name"))
    return d


def list_assessments(conn: Connection, institution_id: int, *, course_id=None, student_id=None, period=None,
                     status="complete", evaluator_user_id=None, text_id=None) -> list[dict]:
    a = db.reading_assessments
    q = _assessment_query().where(a.c.institution_id == institution_id)
    for column, value in ((a.c.course_id, course_id), (a.c.student_id, student_id), (a.c.period, period),
                          (a.c.status, status), (a.c.evaluator_user_id, evaluator_user_id), (a.c.text_id, text_id)):
        if value is not None:
            q = q.where(column == value)
    return [_row(r) for r in conn.execute(q.order_by(a.c.assessed_at.desc(), a.c.id.desc()))]


def _iso(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:  # the reports compare and cut dates as local ISO strings, like the original app
        value = value.astimezone()
    return value.replace(tzinfo=None).isoformat(timespec="seconds")


def _json_text(value):
    return None if value is None else json.dumps(value, ensure_ascii=False)


FRAME_COLUMNS = ["id", "estudiante_id", "texto_id", "fecha", "periodo", "audio_path", "transcripcion",
                 "resultado_json", "pcpm", "ppm", "precision_pct", "errores", "pausas_inesperadas", "categoria",
                 "expresion", "pcpm_ajustado", "observacion", "informe", "evaluador", "marco", "estado", "rasinski",
                 "prosodia_modelo", "rasinski_2", "nombre", "curso", "nivel", "titulo", "course_id"]


def to_frame(rows: list[dict]) -> pd.DataFrame:
    """Assessments in the shape of the original `db.listar_evaluaciones` (Spanish columns, JSON as text)."""
    data = [{
        "id": r["id"], "estudiante_id": r["student_id"], "texto_id": r["text_id"], "fecha": _iso(r["assessed_at"]),
        "periodo": r["period"], "audio_path": r["audio_key"], "transcripcion": r["transcript"],
        "resultado_json": _json_text(r["result"]), "pcpm": r["wcpm"], "ppm": r["wpm"],
        "precision_pct": r["accuracy_pct"], "errores": r["errors"], "pausas_inesperadas": r["unexpected_pauses"],
        "categoria": r["category"], "expresion": r["expression"], "pcpm_ajustado": r["wcpm_adjusted"],
        "observacion": r["observation"], "informe": r["report"], "evaluador": r["evaluator_name"],
        "marco": r["framework"], "estado": STATUS_ES.get(r["status"], r["status"]),
        "rasinski": _json_text(r["rasinski"]), "prosodia_modelo": _json_text(r["prosody_model"]),
        "rasinski_2": _json_text(r["rasinski_2"]), "nombre": r["student_name"], "curso": r["course_name"],
        "nivel": r["level"], "titulo": r["text_title"], "course_id": r["course_id"],
    } for r in rows]
    df = pd.DataFrame(data, columns=FRAME_COLUMNS)
    for col in ("pcpm", "ppm", "precision_pct", "pcpm_ajustado"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    return df


def assessments_frame(conn: Connection, institution_id: int, **filters) -> pd.DataFrame:
    return to_frame(list_assessments(conn, institution_id, **filters))


# --- Jobs --------------------------------------------------------------------------------------

def create_job(conn: Connection, assessment_id: int, kind: str) -> int:
    return conn.execute(insert(db.reading_jobs).values(assessment_id=assessment_id, kind=kind, created_at=now())
                        .returning(db.reading_jobs.c.id)).scalar_one()


def get_job(conn: Connection, institution_id: int, job_id: int) -> dict | None:
    j, a = db.reading_jobs, db.reading_assessments
    row = conn.execute(select(j).select_from(j.join(a, a.c.id == j.c.assessment_id)).where(
        and_(j.c.id == job_id, a.c.institution_id == institution_id))).first()
    return dict(row._mapping) if row else None


def active_job(conn: Connection, assessment_id: int, kind: str) -> dict | None:
    j = db.reading_jobs
    row = conn.execute(select(j).where(and_(j.c.assessment_id == assessment_id, j.c.kind == kind,
                                            j.c.status.in_(("pending", "running")))).order_by(j.c.id.desc())).first()
    return dict(row._mapping) if row else None


def latest_job(conn: Connection, assessment_id: int, kind: str) -> dict | None:
    j = db.reading_jobs
    row = conn.execute(select(j).where(and_(j.c.assessment_id == assessment_id, j.c.kind == kind))
                       .order_by(j.c.id.desc())).first()
    return dict(row._mapping) if row else None


# --- Course synthesis ----------------------------------------------------------------------------

def get_synthesis(conn: Connection, institution_id: int, course_id: int, period: str) -> dict | None:
    s, a = db.reading_course_syntheses, db.reading_assessments
    row = conn.execute(select(s).where(and_(s.c.institution_id == institution_id, s.c.course_id == course_id,
                                            s.c.period == period))).first()
    if not row:
        return None
    # assessments saved after the synthesis make it outdated
    last = conn.execute(select(func.max(a.c.updated_at)).where(and_(
        a.c.institution_id == institution_id, a.c.course_id == course_id, a.c.period == period,
        a.c.status == "complete"))).scalar()
    created = _aware(row.created_at)
    return {"content": row.content, "period": row.period, "createdAt": created.isoformat(),
            "createdBy": row.created_by_email, "outdated": bool(last and _aware(last) > created)}


def save_synthesis(conn: Connection, institution_id: int, course_id: int, period: str, content: str,
                   user_id: int, email: str) -> None:
    s = db.reading_course_syntheses
    where = and_(s.c.institution_id == institution_id, s.c.course_id == course_id, s.c.period == period)
    values = {"content": content, "created_by": user_id, "created_by_email": email, "created_at": now()}
    if conn.execute(update(s).where(where).values(**values)).rowcount == 0:
        conn.execute(insert(s).values(institution_id=institution_id, course_id=course_id, period=period, **values))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes
