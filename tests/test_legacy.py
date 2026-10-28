import csv
import json
import sqlite3

import pytest
from sqlalchemy import func, insert, select

from app import db, legacy
from conftest import make_client, token

# Esquema de lectura_app/core/db.py (la base que tiene cada docente en datos/lectura.db)
LEGACY_SCHEMA = """
CREATE TABLE estudiantes (id INTEGER PRIMARY KEY, nombre TEXT NOT NULL, curso TEXT NOT NULL, nivel INTEGER NOT NULL,
                          activo INTEGER DEFAULT 1, UNIQUE(nombre, curso));
CREATE TABLE textos (id INTEGER PRIMARY KEY, titulo TEXT NOT NULL, nivel INTEGER NOT NULL, contenido TEXT NOT NULL,
                     palabras INTEGER NOT NULL, creado TEXT NOT NULL);
CREATE TABLE evaluaciones (id INTEGER PRIMARY KEY, estudiante_id INTEGER NOT NULL REFERENCES estudiantes(id),
    texto_id INTEGER NOT NULL REFERENCES textos(id), fecha TEXT NOT NULL, periodo TEXT, audio_path TEXT, transcripcion TEXT,
    resultado_json TEXT, pcpm REAL, ppm REAL, precision_pct REAL, errores INTEGER, pausas_inesperadas INTEGER,
    categoria TEXT, expresion INTEGER, pcpm_ajustado REAL, observacion TEXT, informe TEXT, evaluador TEXT, marco TEXT,
    estado TEXT DEFAULT 'completa', rasinski TEXT, prosodia_modelo TEXT, rasinski_2 TEXT);
"""
RESULT = json.dumps({"detalle": [{"ref": "La", "leido": "la", "tipo": "correcta", "inicio": 0, "fin": 0.3}],
                     "pcpm": 120.0, "ppm": 121.0, "precision_pct": 98.0, "errores": 1, "revisar": 0})


@pytest.fixture
def legacy_db(tmp_path, engine):
    with engine.begin() as c:  # dos "Luis Rojas" en el colegio: el emparejamiento por nombre es ambiguo
        c.execute(insert(db.cs_courses), [{"id": 102, "institution_id": 1, "cycle_type_level_id": 6, "letter": "A"}])
        c.execute(insert(db.cs_students), [
            {"id": 1003, "institution_id": 1, "course_id": 102, "name": "Luis", "last_name": "Rojas"},
            {"id": 1004, "institution_id": 1, "course_id": 100, "name": "Luis", "last_name": "Rojas"}])
    path = tmp_path / "lectura.db"
    con = sqlite3.connect(path)
    con.executescript(LEGACY_SCHEMA)
    con.executemany("INSERT INTO estudiantes (id, nombre, curso, nivel) VALUES (?, ?, ?, ?)", [
        (1, "ana perez", "5°A", 5),          # sin tildes ni mayúsculas
        (2, "Soto Beto", "5° A", 5),          # apellido primero
        (3, "Carla Mena", "4°B", 4),          # el 4°B no existe en Colegio Smart: hoy está en otro curso
        (4, "Pedro Nadie", "5°A", 5),         # no existe
        (5, "Luis Rojas", "7°C", 7),          # dos candidatos
    ])
    con.executemany("INSERT INTO textos (id, titulo, nivel, contenido, palabras, creado) VALUES (?, ?, ?, ?, ?, ?)", [
        (1, "El parque", 5, "La casa es grande.", 4, "2026-03-10T09:00:00"),
        (2, "Los ríos", 4, "Los ríos de Chile son cortos.", 6, "2026-03-10T09:00:00")])
    audios = tmp_path / "audios"
    audios.mkdir()
    (audios / "1_20260410_100000.webm").write_bytes(b"audio")
    con.executemany("""INSERT INTO evaluaciones (id, estudiante_id, texto_id, fecha, periodo, audio_path, resultado_json,
                       pcpm, ppm, precision_pct, errores, categoria, expresion, pcpm_ajustado, evaluador, marco, estado,
                       rasinski, prosodia_modelo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", [
        (1, 1, 1, "2026-04-10T10:00:00", "2026-04", r"C:\\Users\\Profe\\lectura_app\\datos\\audios\\1_20260410_100000.webm",
         RESULT, 120.0, 121.0, 98.0, 1, "Media baja", 4, 125.0, "Prof. Rojas", "astoreca", "completa", "[3,3,2,4]",
         json.dumps({"version": "v1", "puntajes": [3, 3, 2, 4]})),
        (2, 1, 1, "2026-10-10T10:00:00", "2026-10", "/x/no_existe.webm", RESULT, 140.0, 141.0, 99.0, 0, "Media alta", 5,
         None, "Prof. Rojas", "astoreca", "completa", None, None),
        (3, 1, 1, "2026-10-11T10:00:00", "2026-10", None, RESULT, 10.0, 10.0, 50.0, 9, None, None, None, None,
         "astoreca", "borrador", None, None),                                   # borrador: no se importa
        (4, 2, 1, "2026-04-11T10:00:00", "2026-04", None, RESULT, 90.0, 90.0, 95.0, 2, "Lenta", 3, None, None,
         None, None, None, None),                                               # anterior a marcos y estado
        (5, 3, 2, "2026-04-12T10:00:00", "2026-04", None, RESULT, 80.0, 80.0, 95.0, 2, "Lenta", 3, None, None,
         "mineduc", "completa", None, None),
        (6, 4, 1, "2026-04-12T10:00:00", "2026-04", None, RESULT, 80.0, 80.0, 95.0, 2, "Lenta", 3, None, None,
         "mineduc", "completa", None, None),
        (7, 5, 1, "2026-04-12T10:00:00", "2026-04", None, RESULT, 80.0, 80.0, 95.0, 2, "Lenta", 3, None, None,
         "mineduc", "completa", None, None),
    ])
    con.commit()
    con.close()
    return path, audios


def _count(engine, table):
    with engine.begin() as c:
        return c.execute(select(func.count()).select_from(table)).scalar_one()


def test_parse_course_and_names():
    assert legacy.parse_course("5°A") == (5, "A")
    assert legacy.parse_course("5° a") == (5, "A")
    assert legacy.parse_course("6to B") == (6, "B")
    assert legacy.parse_course("5° Básico A") == (5, "A")
    assert legacy.parse_course("8") == (8, None)
    assert legacy.normalize_name("  José  Muñoz-Peña ") == "jose muñoz peña"
    assert legacy.name_tokens("Soto Beto") == legacy.name_tokens("beto soto")


def test_dry_run_writes_nothing(legacy_db, engine, fake_storage, tmp_path):
    path, audios = legacy_db
    before = path.read_bytes()
    s = legacy.import_legacy(str(path), 1, audios_dir=str(audios))
    assert not s.applied and s.assessments_imported == 4 and s.texts_created == 2
    assert _count(engine, db.reading_assessments) == 0 and _count(engine, db.reading_texts) == 0
    assert fake_storage.uploaded == [] and path.read_bytes() == before  # tampoco sube audio ni toca el SQLite
    assert {m.legacy_id: m.status for m in s.students} == {
        1: "matched", 2: "matched", 3: "matched_other_course", 4: "unmatched", 5: "ambiguous"}


def test_apply_imports_and_is_idempotent(legacy_db, engine, fake_storage, tmp_path):
    path, audios = legacy_db
    s = legacy.import_legacy(str(path), 1, audios_dir=str(audios), evaluator_user_id=10, apply=True)
    assert s.assessments_imported == 4 and s.audio_uploaded == 1 and s.audio_missing == 1
    ana = next(m for m in s.students if m.legacy_id == 1)
    assert (ana.found, ana.imported, ana.drafts) == (3, 2, 1)
    assert fake_storage.uploaded[0][0] == "1_20260410_100000.webm" and fake_storage.uploaded[0][2] == "audio/webm"

    with engine.begin() as c:
        rows = {a["source_id"]: a for a in (dict(x._mapping) for x in c.execute(select(db.reading_assessments)))}
    first = rows[1]
    assert first["student_id"] == 1000 and first["course_id"] == 100 and first["course_name"] == "5° Básico A"
    assert first["wcpm_adjusted"] == 125.0 and first["rasinski"] == [3, 3, 2, 4]
    assert first["prosody_model"]["puntajes"] == [3, 3, 2, 4] and first["audio_key"].startswith("reading-audio/1/")
    assert first["evaluator_user_id"] == 10 and first["status"] == "complete"
    assert str(first["assessed_at"]).startswith("2026-04-10")
    assert rows[4]["framework"] == "mineduc" and rows[4]["student_id"] == 1001
    carla = rows[5]
    assert carla["student_id"] == 1002 and carla["course_name"] == "1° Medio A" and carla["level"] == 4

    again = legacy.import_legacy(str(path), 1, audios_dir=str(audios), apply=True)
    assert again.assessments_imported == 0 and again.texts_created == 0
    assert sum(m.skipped_existing for m in again.students) == 4
    assert _count(engine, db.reading_assessments) == 4

    # los reportes funcionan sobre lo importado
    r = make_client(token()).get("/api/lectura/reports/students/1000").json()
    assert [h["wcpm"] for h in r["history"]] == [125, 140]


def test_report_and_manual_mapping(legacy_db, engine, fake_storage, tmp_path):
    path, _ = legacy_db
    s = legacy.import_legacy(str(path), 1)
    report = tmp_path / "emparejamiento.csv"
    legacy.write_report(s, str(report))
    with open(report, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0].keys() >= {"legacy_id", "student_id", "estado"}
    assert {r["legacy_id"]: r["estado"] for r in rows}["5"] == "ambiguo"
    # el docente completa student_id de los pendientes y reusa el archivo como --mapping
    mapping = tmp_path / "mapa.csv"
    mapping.write_text("legacy_id,student_id\n4,1001\n5,1003\n9,999\n", encoding="utf-8")
    s2 = legacy.import_legacy(str(path), 1, mapping_path=str(mapping), apply=True)
    by_id = {m.legacy_id: m for m in s2.students}
    assert by_id[4].status == "manual" and by_id[4].student_id == 1001
    assert by_id[5].status == "manual" and by_id[5].course_name == "6° Básico A"
    assert s2.assessments_imported == 6


def test_mapping_to_other_institution_is_ignored(legacy_db, engine, fake_storage, tmp_path):
    path, _ = legacy_db
    mapping = tmp_path / "mapa.csv"
    mapping.write_text("legacy_id,student_id\n4,2000\n", encoding="utf-8")  # 2000 es de la institución 2
    s = legacy.import_legacy(str(path), 1, mapping_path=str(mapping))
    assert next(m for m in s.students if m.legacy_id == 4).status == "unmatched"


def test_rejects_other_files(tmp_path, engine):
    other = tmp_path / "otra.db"
    sqlite3.connect(other).execute("CREATE TABLE x (id INTEGER)").connection.commit()
    with pytest.raises(ValueError, match="lectura_app"):
        legacy.import_legacy(str(other), 1)
