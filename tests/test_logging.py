import json
import logging
import time

import pytest

from app import logging_config
from conftest import make_client, token


def _lines(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]


def test_formatter_emits_json_with_context(capsys):
    logging_config.setup_logging("INFO", json_output=True)
    ctx_token = logging_config.request_context.set({"traceId": "abc", "userId": 7})
    try:
        logging.getLogger("lectura.test").info("hola", extra={"jobId": 3})
        try:
            raise ValueError("boom")
        except ValueError:
            logging.getLogger("lectura.test").exception("falló")
    finally:
        logging_config.request_context.reset(ctx_token)
    info, error = _lines(capsys)
    assert info["message"] == "hola" and info["level"] == "INFO" and info["service"] == "lectura-api"
    assert info["traceId"] == "abc" and info["userId"] == 7 and info["jobId"] == 3
    assert error["level"] == "ERROR" and "ValueError: boom" in error["exception"]


def test_access_log_has_user_trace_and_status(client, capsys):
    logging_config.setup_logging("INFO", json_output=True)
    client.get("/api/lectura/me", headers={"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"})
    access = [e for e in _lines(capsys) if e["logger"] == "lectura.access"]
    assert len(access) == 1
    e = access[0]
    assert e["path"] == "/api/lectura/me" and e["status"] == 200 and e["method"] == "GET"
    assert e["traceId"] == "4bf92f3577b34da6a3ce929d0e0e4736" and e["userId"] == 10 and e["institutionId"] == 1
    assert "email" not in e and e["durationMs"] >= 0


def test_access_log_for_rejected_request_and_quiet_health(engine, fake_storage, capsys):
    logging_config.setup_logging("INFO", json_output=True)
    anonymous = make_client()
    assert anonymous.get("/api/lectura/me").status_code == 401
    anonymous.get("/actuator/health")
    access = [e for e in _lines(capsys) if e["logger"] == "lectura.access"]
    assert [(e["path"], e["status"]) for e in access] == [("/api/lectura/me", 401)]
    assert "userId" not in access[0] and access[0]["traceId"]


def test_access_log_route_is_template_while_path_keeps_real_id(client, capsys):
    logging_config.setup_logging("INFO", json_output=True)
    client.get("/api/lectura/courses/82/students")
    e = [x for x in _lines(capsys) if x["logger"] == "lectura.access"][0]
    assert e["path"] == "/api/lectura/courses/82/students"
    assert e["route"] == "/api/lectura/courses/{course_id}/students"


def test_access_log_omits_route_for_404_and_csrf_403(engine, fake_storage, client, capsys):
    logging_config.setup_logging("INFO", json_output=True)
    anonymous = make_client()
    assert anonymous.get("/api/lectura/me").status_code == 401
    assert client.get("/api/lectura/no-existe/7").status_code == 404
    del client.headers["X-XSRF-TOKEN"]
    assert client.post("/api/lectura/texts", json={}).status_code == 403
    access = [x for x in _lines(capsys) if x["logger"] == "lectura.access"]
    assert [x["status"] for x in access] == [401, 404, 403]
    assert all("route" not in x for x in access[1:])
    # a 401 raised by an auth dependency already matched its route, so it does carry the template
    assert access[0]["route"] == ("/api/lectura/me")


def test_no_email_in_any_log_line(client, capsys):
    logging_config.setup_logging("INFO", json_output=True)
    client.get("/api/lectura/me")
    assert "@colegio.cl" not in capsys.readouterr().out


# --- Log levels by severity ---------------------------------------------------------------------

def _auth_records(caplog):
    return [r for r in caplog.records if r.name == "lectura.auth"]


def test_expired_token_is_info(caplog):
    from app import security
    caplog.set_level(logging.INFO)
    expired = token(exp=int(time.time()) - 60)
    with pytest.raises(Exception):
        security.decode_token(expired)
    [rec] = _auth_records(caplog)
    assert rec.levelno == logging.INFO and "ExpiredSignatureError" in rec.getMessage()
    assert expired not in rec.getMessage()


def test_token_with_bad_signature_is_warning(caplog):
    import jwt
    from app import security
    caplog.set_level(logging.INFO)
    forged = jwt.encode({"iss": "colegio-smart-api", "aud": "colegio-smart-app", "exp": 9999999999},
                        "another-secret-another-secret-another-123", algorithm="HS256")
    with pytest.raises(Exception):
        security.decode_token(forged)
    [rec] = _auth_records(caplog)
    assert rec.levelno == logging.WARNING and forged not in rec.getMessage()


def test_request_without_cookie_is_info(engine, fake_storage, caplog):
    caplog.set_level(logging.INFO)
    assert make_client().get("/api/lectura/me").status_code == 401
    [rec] = _auth_records(caplog)
    assert rec.levelno == logging.INFO and "no auth cookie" in rec.getMessage()


def test_storage_exists_is_silent_on_404_and_warns_on_other_errors(monkeypatch, caplog):
    from types import SimpleNamespace

    from botocore.exceptions import ClientError

    from app import storage
    caplog.set_level(logging.DEBUG)

    def client_raising(exc):
        def head_object(**kw):
            raise exc
        return SimpleNamespace(head_object=head_object)

    for code in ("404", "NoSuchKey", "NotFound"):
        monkeypatch.setattr(storage, "_client", lambda code=code: client_raising(
            ClientError({"Error": {"Code": code}}, "HeadObject")))
        assert storage.exists("k") is False
    assert not [r for r in caplog.records if r.name == "lectura.storage"]

    for exc in (ClientError({"Error": {"Code": "403"}}, "HeadObject"), TimeoutError("timeout")):
        monkeypatch.setattr(storage, "_client", lambda exc=exc: client_raising(exc))
        assert storage.exists("k") is False
    records = [r for r in caplog.records if r.name == "lectura.storage"]
    assert len(records) == 2 and all(r.levelno == logging.WARNING and r.exc_info for r in records)
