"""Database tables. The schema is created by migrations/*.sql (no auto-DDL in production, like api-colegio-smart).

Two metadata objects:
- `metadata`: tables owned by this service (prefix reading_).
- `cs_metadata`: the subset of api-colegio-smart tables this service reads. Owned by api-colegio-smart: read-only here,
  declared only with the columns we use. Tests create both on SQLite.
"""
from sqlalchemy import (JSON, BigInteger, Column, DateTime, Float, ForeignKey, Integer, MetaData, SmallInteger,
                        String, Table, Text, UniqueConstraint, create_engine, func)
from sqlalchemy.dialects.postgresql import JSONB

from app.settings import settings

Json = JSON().with_variant(JSONB(), "postgresql")
# SQLite only autoincrements INTEGER PRIMARY KEY; Postgres uses BIGSERIAL (see the migration).
Id = BigInteger().with_variant(Integer(), "sqlite")

metadata = MetaData()
cs_metadata = MetaData()

# --- api-colegio-smart (read-only) ------------------------------------------------------------

cs_institutions = Table("institutions", cs_metadata, Column("id", Id, primary_key=True))
cs_users = Table(
    "users", cs_metadata,
    Column("id", Id, primary_key=True),
    Column("institution_id", BigInteger),
    Column("password_changed_at", DateTime(timezone=True)),
)
cs_cycle_type_levels = Table(
    "cycles_types_levels", cs_metadata,
    Column("id", Id, primary_key=True),
    Column("name", String),
)
cs_courses = Table(
    "courses", cs_metadata,
    Column("id", Id, primary_key=True),
    Column("institution_id", BigInteger),
    Column("cycle_type_level_id", BigInteger),
    Column("letter", String),
)
cs_students = Table(
    "students", cs_metadata,
    Column("id", Id, primary_key=True),
    Column("institution_id", BigInteger),
    Column("course_id", BigInteger),
    Column("name", String),
    Column("last_name", String),
)

# --- Lectura -----------------------------------------------------------------------------------

reading_texts = Table(
    "reading_texts", metadata,
    Column("id", Id, primary_key=True),
    Column("institution_id", BigInteger, nullable=False),
    Column("title", Text, nullable=False),
    Column("level", SmallInteger, nullable=False),
    Column("content", Text, nullable=False),
    Column("word_count", Integer, nullable=False),
    Column("created_by", BigInteger),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # origin of imported rows (migrations/002): "lectura_app" + id in the teacher's SQLite
    Column("source", Text),
    Column("source_id", BigInteger),
)

reading_assessments = Table(
    "reading_assessments", metadata,
    Column("id", Id, primary_key=True),
    Column("institution_id", BigInteger, nullable=False),
    Column("student_id", BigInteger, nullable=False),
    Column("course_id", BigInteger),
    Column("text_id", BigInteger, ForeignKey("reading_texts.id"), nullable=False),
    Column("evaluator_user_id", BigInteger),
    # Snapshot at assessment time: the student may change course later, the history keeps the original one.
    Column("course_name", Text, nullable=False),
    Column("level", SmallInteger, nullable=False),
    Column("assessed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("period", Text),
    Column("audio_key", Text),
    Column("audio_mime", Text),
    Column("transcript", Text),
    Column("result", Json),
    Column("wcpm", Float),
    Column("wpm", Float),
    Column("accuracy_pct", Float),
    Column("errors", Integer),
    Column("unexpected_pauses", Integer),
    Column("category", Text),
    Column("expression", SmallInteger),
    Column("wcpm_adjusted", Float),
    Column("observation", Text),
    Column("report", Text),
    Column("evaluator_name", Text),
    Column("framework", Text),
    Column("status", Text, nullable=False, server_default="draft"),  # draft | complete
    Column("rasinski", Json),
    Column("rasinski_2", Json),
    Column("prosody_model", Json),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("source", Text),
    Column("source_id", BigInteger),
)

reading_course_syntheses = Table(
    "reading_course_syntheses", metadata,
    Column("id", Id, primary_key=True),
    Column("institution_id", BigInteger, nullable=False),
    Column("course_id", BigInteger, nullable=False),
    Column("period", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("created_by", BigInteger),
    Column("created_by_email", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("institution_id", "course_id", "period"),
)

reading_jobs = Table(
    "reading_jobs", metadata,
    Column("id", Id, primary_key=True),
    Column("assessment_id", BigInteger, ForeignKey("reading_assessments.id", ondelete="CASCADE"), nullable=False),
    Column("kind", Text, nullable=False),  # analyze | prosody
    Column("status", Text, nullable=False, server_default="pending"),  # pending | running | done | error
    Column("error", Text),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
)


def make_engine(url: str | None = None):
    url = url or settings.database_url
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:  # Supabase pooler: no server-side prepared statements (api-colegio-smart uses prepareThreshold=0)
        kwargs["connect_args"] = {"prepare_threshold": None}
    return create_engine(url, **kwargs)


engine = make_engine()
