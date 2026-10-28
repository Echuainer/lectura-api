"""Import of a lectura_app SQLite database (datos/lectura.db on a teacher's PC) into lectura-api.

The local students are matched to the Colegio Smart students of the institution; their complete assessments,
the texts they used and (optionally) their audio are copied. Re-running it skips what was already imported
(source = "lectura_app", source_id = id in the SQLite). Drafts are not imported.
"""
import csv
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import and_, insert, select

from app import db, repository, storage
from core.analisis import tokenizar_referencia

SOURCE = "lectura_app"
LOCAL_TZ = ZoneInfo("America/Santiago")  # lectura_app saved naive local times
STATUS = {"completa": "complete", None: "complete"}  # rows from before the "estado" column are complete


def normalize_name(name: str | None) -> str:
    """lowercase, no accents (ñ stays), single spaces."""
    text = unicodedata.normalize("NFD", (name or "").lower().replace("ñ", "\0"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn").replace("\0", "ñ")
    return " ".join(re.sub(r"[^\wñ ]", " ", text).split())


def name_tokens(name: str | None) -> frozenset[str]:
    return frozenset(normalize_name(name).split())


def parse_course(course: str | None) -> tuple[int | None, str | None]:
    """lectura_app course label → (level, letter): "5°A", "5° A", "5A", "5to B", "5° Básico A"."""
    text = normalize_name((course or "").replace("°", " ").replace("º", " "))
    m = re.match(r"(\d+)\s*(?:to|vo|ro|do|mo|no|er)?\s*(?:basico\s*)?([a-z])?\b", text)
    if not m:
        return repository.parse_level(course), None
    return int(m.group(1)), (m.group(2) or None) and m.group(2).upper()


@dataclass
class StudentMatch:
    legacy_id: int
    name: str
    course: str
    level: int
    status: str = "unmatched"  # matched | matched_other_course | manual | ambiguous | unmatched
    student_id: int | None = None
    student_name: str = ""
    course_id: int | None = None  # Colegio Smart course of the legacy course (level + letter), when it exists
    course_name: str = ""
    found: int = 0
    imported: int = 0
    skipped_existing: int = 0
    drafts: int = 0


@dataclass
class Summary:
    students: list[StudentMatch] = field(default_factory=list)
    texts_created: int = 0
    assessments_imported: int = 0
    audio_uploaded: int = 0
    audio_missing: int = 0
    applied: bool = False

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.students:
            out[s.status] = out.get(s.status, 0) + 1
        return out


def read_legacy(path: str) -> tuple[list[dict], list[dict], list[dict]]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)  # never modifies the teacher's file
    con.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        missing = {"estudiantes", "textos", "evaluaciones"} - tables
        if missing:
            raise ValueError(f"No parece una base de lectura_app: faltan las tablas {sorted(missing)}")
        rows = lambda table: [dict(r) for r in con.execute(f"SELECT * FROM {table}")]  # noqa: E731
        return rows("estudiantes"), rows("textos"), rows("evaluaciones")
    finally:
        con.close()


def read_mapping(path: str | None) -> dict[int, int]:
    """Manual matches: CSV with columns legacy_id,student_id (the report's columns can be reused)."""
    if not path:
        return {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {int(r["legacy_id"]): int(r["student_id"]) for r in csv.DictReader(f)
                if (r.get("legacy_id") or "").strip() and (r.get("student_id") or "").strip()}


def _directory(conn, institution_id: int):
    """Colegio Smart courses and students of the institution."""
    courses = repository.list_courses(conn, institution_id)
    by_course, everyone = {}, []
    for c in courses:
        by_course[c["id"]] = repository.list_students(conn, institution_id, c["id"])
        everyone += [s | {"courseId": c["id"], "courseName": c["name"]} for s in by_course[c["id"]]]
    return courses, by_course, everyone


def _find(candidates: list[dict], name: str) -> list[dict]:
    exact = [s for s in candidates if normalize_name(s["name"]) == normalize_name(name)]
    if exact:
        return exact
    tokens = name_tokens(name)
    return [s for s in candidates if name_tokens(s["name"]) == tokens]  # same words, other order


def match_students(conn, institution_id: int, legacy_students: list[dict], mapping: dict[int, int]) -> list[StudentMatch]:
    courses, by_course, everyone = _directory(conn, institution_id)
    by_id = {s["id"]: s for s in everyone}
    out = []
    for e in legacy_students:
        m = StudentMatch(legacy_id=e["id"], name=e["nombre"], course=e["curso"], level=int(e["nivel"]))
        level, letter = parse_course(e["curso"])
        level = level or m.level
        same_course = [c for c in courses if c["level"] == level and (letter is None or c["name"].upper().endswith(f" {letter}"))]
        if len(same_course) == 1:
            m.course_id, m.course_name = same_course[0]["id"], same_course[0]["name"]
        if e["id"] in mapping:
            s = by_id.get(mapping[e["id"]])
            if s:
                m.status, m.student_id, m.student_name = "manual", s["id"], s["name"]
                m.course_id = m.course_id or s["courseId"]
                m.course_name = m.course_name or s["courseName"]
            out.append(m)
            continue
        found = _find([s for c in same_course for s in by_course[c["id"]]], e["nombre"])
        status = "matched"
        if not found:
            found, status = _find(everyone, e["nombre"]), "matched_other_course"
        if len(found) == 1:
            s = found[0]
            m.status, m.student_id, m.student_name = status, s["id"], s["name"]
            if m.course_id is None:  # the legacy course no longer exists: keep the student's current one
                m.course_id, m.course_name = by_id[s["id"]]["courseId"], by_id[s["id"]]["courseName"]
        elif len(found) > 1:
            m.status = "ambiguous"
        out.append(m)
    return out


def _existing_ids(conn, table, institution_id: int) -> dict[int, int]:
    rows = conn.execute(select(table.c.source_id, table.c.id).where(
        and_(table.c.institution_id == institution_id, table.c.source == SOURCE))).all()
    return dict(rows)


def _parse_json(text, kind):
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, kind) else None


def _local_datetime(text: str | None) -> datetime:
    value = datetime.fromisoformat(text) if text else datetime.now()
    return value if value.tzinfo else value.replace(tzinfo=LOCAL_TZ)


def _audio_file(audio_path: str | None, audios_dir: str | None) -> Path | None:
    """The SQLite keeps absolute paths of the teacher's PC: the file is looked up by name in audios_dir."""
    if not audio_path or not audios_dir:
        return None
    candidate = Path(audios_dir) / Path(audio_path.replace("\\", "/")).name
    return candidate if candidate.is_file() else None


def import_legacy(sqlite_path: str, institution_id: int, *, audios_dir: str | None = None,
                  mapping_path: str | None = None, evaluator_user_id: int | None = None,
                  apply: bool = False) -> Summary:
    legacy_students, legacy_texts, legacy_assessments = read_legacy(sqlite_path)
    summary = Summary(applied=apply)
    texts_by_id = {t["id"]: t for t in legacy_texts}
    conn = db.engine.connect()
    tx = conn.begin()
    try:
        summary.students = match_students(conn, institution_id, legacy_students, read_mapping(mapping_path))
        matches = {m.legacy_id: m for m in summary.students}
        existing_texts = _existing_ids(conn, db.reading_texts, institution_id)
        existing_assessments = _existing_ids(conn, db.reading_assessments, institution_id)
        for e in sorted(legacy_assessments, key=lambda x: (x.get("fecha") or "", x["id"])):
            m = matches.get(e["estudiante_id"])
            if m is None:
                continue
            m.found += 1
            if e.get("estado") not in STATUS:
                m.drafts += 1
                continue
            if m.student_id is None:
                continue
            if e["id"] in existing_assessments:
                m.skipped_existing += 1
                continue
            text_id = existing_texts.get(e["texto_id"])
            if text_id is None:
                t = texts_by_id[e["texto_id"]]
                text_id = conn.execute(insert(db.reading_texts).values(
                    institution_id=institution_id, title=t["titulo"].strip(), level=int(t["nivel"]),
                    content=t["contenido"], word_count=len(tokenizar_referencia(t["contenido"])),
                    created_by=evaluator_user_id, created_at=_local_datetime(t.get("creado")),
                    updated_at=repository.now(), source=SOURCE, source_id=t["id"]).returning(db.reading_texts.c.id)).scalar_one()
                existing_texts[e["texto_id"]] = text_id
                summary.texts_created += 1
            audio_key = audio_mime = None
            audio = _audio_file(e.get("audio_path"), audios_dir)
            if audio is not None:
                audio_mime = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4", "ogg": "audio/ogg",
                              "webm": "audio/webm"}.get(audio.suffix.lstrip(".").lower(), "audio/webm")
                audio_key = storage.new_key(institution_id, audio_mime)
                if apply:
                    storage.upload_file(str(audio), audio_key, audio_mime)
                summary.audio_uploaded += 1
            elif e.get("audio_path"):
                summary.audio_missing += 1
            conn.execute(insert(db.reading_assessments).values(
                institution_id=institution_id, student_id=m.student_id, course_id=m.course_id, text_id=text_id,
                evaluator_user_id=evaluator_user_id, course_name=m.course_name or m.course, level=m.level,
                assessed_at=_local_datetime(e.get("fecha")), period=e.get("periodo"), audio_key=audio_key,
                audio_mime=audio_mime, transcript=e.get("transcripcion"), result=_parse_json(e.get("resultado_json"), dict),
                wcpm=e.get("pcpm"), wpm=e.get("ppm"), accuracy_pct=e.get("precision_pct"), errors=e.get("errores"),
                unexpected_pauses=e.get("pausas_inesperadas"), category=e.get("categoria"), expression=e.get("expresion"),
                wcpm_adjusted=e.get("pcpm_ajustado"), observation=e.get("observacion"), report=e.get("informe"),
                evaluator_name=e.get("evaluador"), framework=e.get("marco") or "mineduc", status="complete",
                rasinski=_parse_json(e.get("rasinski"), list), rasinski_2=_parse_json(e.get("rasinski_2"), list),
                prosody_model=_parse_json(e.get("prosodia_modelo"), dict),
                created_at=repository.now(), updated_at=repository.now(), source=SOURCE, source_id=e["id"]))
            m.imported += 1
            summary.assessments_imported += 1
        if apply:
            tx.commit()
        else:
            tx.rollback()  # dry run: same checks and counts, nothing is written
    except Exception:
        tx.rollback()
        raise
    finally:
        conn.close()
    return summary


REPORT_COLUMNS = ["legacy_id", "nombre", "curso", "nivel", "estado", "student_id", "estudiante_colegio_smart",
                  "curso_colegio_smart", "evaluaciones", "importadas", "ya_importadas", "borradores_omitidos"]
STATUS_ES = {"matched": "emparejado", "matched_other_course": "emparejado en otro curso", "manual": "manual",
             "ambiguous": "ambiguo", "unmatched": "sin pareja"}


def write_report(summary: Summary, path: str) -> None:
    """One row per local student. Fill student_id for the ambiguous / unmatched ones and pass it back as --mapping."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(REPORT_COLUMNS)
        for s in summary.students:
            w.writerow([s.legacy_id, s.name, s.course, s.level, STATUS_ES[s.status], s.student_id or "", s.student_name,
                        s.course_name, s.found, s.imported, s.skipped_existing, s.drafts])
