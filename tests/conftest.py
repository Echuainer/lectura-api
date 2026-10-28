import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# before importing app: settings are read once
os.environ.update(JWT_SECRET="test-secret-test-secret-test-secret-123", WORKER_ENABLED="false",
                  CSRF_COOKIE_SECURE="false", DATABASE_URL="sqlite://")

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import insert  # noqa: E402

from app import db, security, storage  # noqa: E402

SECRET = os.environ["JWT_SECRET"]
CSRF = "csrf-test-token"


def token(user_id=10, institution_id=1, role=security.DOCENTE, algorithm="HS256", **extra):
    claims = {"iss": "colegio-smart-api", "aud": "colegio-smart-app", "sub": f"user{user_id}@colegio.cl",
              "userId": user_id, "institutionId": institution_id, "institutionRoleId": role, "enabled": True,
              "permissions": {"lectura": True}, "exp": int(time.time()) + 3600, "iat": int(time.time())}
    claims.update(extra)
    return jwt.encode(claims, SECRET, algorithm=algorithm)


class FakeStorage:
    def __init__(self):
        self.objects, self.deleted, self.uploaded, self.modified = set(), [], [], {}

    def upload_url(self, key, mime):
        return f"https://r2.test/put/{key}"

    def download_url(self, key):
        return f"https://r2.test/get/{key}"

    def exists(self, key):
        return key in self.objects

    def download(self, key, folder):
        path = Path(folder) / Path(key).name
        path.write_bytes(b"audio")
        return str(path)

    def delete(self, key):
        self.deleted.append(key)
        self.objects.discard(key)

    def upload_file(self, path, key, mime):
        self.uploaded.append((Path(path).name, key, mime))
        self.objects.add(key)

    def list_keys(self, prefix):
        return [(k, self.modified.get(k, datetime(2026, 1, 1, tzinfo=timezone.utc))) for k in sorted(self.objects)
                if k.startswith(prefix)]


ROOT = Path(__file__).resolve().parent.parent
# TEST_DATABASE_URL=postgresql+psycopg://... runs the suite on Postgres with the real migrations (wipes the schema)
PG_URL = os.environ.get("TEST_DATABASE_URL")


def _create_schema(e):
    if not PG_URL:
        db.cs_metadata.create_all(e)
        db.metadata.create_all(e)
        return
    with e.begin() as c:
        c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        c.exec_driver_sql((ROOT / "tests" / "cs_stub.sql").read_text())
        for migration in sorted((ROOT / "migrations").glob("*.sql")):
            c.exec_driver_sql(migration.read_text())


@pytest.fixture
def engine(tmp_path, monkeypatch):
    e = db.make_engine(PG_URL or f"sqlite:///{tmp_path / 'test.db'}")
    _create_schema(e)
    monkeypatch.setattr(db, "engine", e)
    security.stamp_cache.clear()
    with e.begin() as c:
        c.execute(insert(db.cs_institutions), [{"id": 1}, {"id": 2}])
        c.execute(insert(db.cs_users), [
            {"id": 10, "institution_id": 1, "password_changed_at": None},
            {"id": 11, "institution_id": 1, "password_changed_at": None},
            {"id": 12, "institution_id": 1, "password_changed_at": None},
            {"id": 20, "institution_id": 2, "password_changed_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        ])
        c.execute(insert(db.cs_cycle_type_levels), [{"id": 5, "name": "5° Básico"}, {"id": 6, "name": "6° Básico"},
                                                     {"id": 9, "name": "1° Medio"}])
        c.execute(insert(db.cs_courses), [
            {"id": 100, "institution_id": 1, "cycle_type_level_id": 5, "letter": "A"},
            {"id": 101, "institution_id": 1, "cycle_type_level_id": 9, "letter": "A"},
            {"id": 200, "institution_id": 2, "cycle_type_level_id": 6, "letter": "B"},
        ])
        c.execute(insert(db.cs_students), [
            {"id": 1000, "institution_id": 1, "course_id": 100, "name": "Ana", "last_name": "Pérez"},
            {"id": 1001, "institution_id": 1, "course_id": 100, "name": "Beto", "last_name": "Soto"},
            {"id": 1002, "institution_id": 1, "course_id": 101, "name": "Carla", "last_name": "Mena"},
            {"id": 2000, "institution_id": 2, "course_id": 200, "name": "Diego", "last_name": "Ríos"},
        ])
    return e


@pytest.fixture
def fake_storage(monkeypatch):
    fake = FakeStorage()
    for name in ("upload_url", "download_url", "exists", "download", "delete", "upload_file", "list_keys"):
        monkeypatch.setattr(storage, name, getattr(fake, name))
    return fake


def make_client(tok=None):
    from app.main import app
    client = TestClient(app)
    client.cookies.set("XSRF-TOKEN", CSRF)
    client.headers["X-XSRF-TOKEN"] = CSRF
    if tok:
        client.cookies.set("cs_session", tok)
    return client


@pytest.fixture
def client(engine, fake_storage):
    return make_client(token())
