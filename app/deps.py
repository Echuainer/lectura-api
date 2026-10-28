"""Shared FastAPI dependencies."""
import unicodedata
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import Response

from app import db, repository


def get_conn():
    """One transaction per request: committed when the endpoint returns, rolled back on error."""
    with db.engine.begin() as conn:
        yield conn


def course_or_404(conn, institution_id: int, course_id: int) -> dict:
    course = repository.get_course(conn, institution_id, course_id)
    if course is None:
        raise HTTPException(404, "Curso no encontrado")
    course["studentCount"] = len(repository.list_students(conn, institution_id, course_id))
    return course


def assessment_or_404(conn, institution_id: int, assessment_id: int) -> dict:
    a = repository.get_assessment(conn, institution_id, assessment_id)
    if a is None:
        raise HTTPException(404, "Evaluación no encontrada")
    return a


def bad_request(e: Exception) -> HTTPException:
    return HTTPException(400, str(e))


def download(content: bytes, filename: str, media_type: str) -> Response:
    # names carry "5°" or accents: ASCII fallback plus the UTF-8 name (RFC 5987)
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode() or "descarga"
    disposition = f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'
    return Response(content, media_type=media_type, headers={"Content-Disposition": disposition})


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MARKDOWN = "text/markdown; charset=utf-8"
