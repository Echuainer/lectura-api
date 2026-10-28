from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app import db, sweep
from test_api import _assess, engine_ok  # noqa: F401 (fixture)


def test_sweep_deletes_only_old_unreferenced_audio(client, fake_storage, engine_ok):  # noqa: F811
    assessment_id, _ = _assess(client, fake_storage)
    kept = next(iter(fake_storage.objects))
    old = datetime.now(timezone.utc) - timedelta(days=3)
    fake_storage.objects |= {"reading-audio/1/huerfano.webm", "reading-audio/2/reciente.webm", "otro/prefijo.webm"}
    fake_storage.modified = {kept: old, "reading-audio/1/huerfano.webm": old,
                             "reading-audio/2/reciente.webm": datetime.now(timezone.utc)}

    dry = sweep.sweep()
    assert dry.orphans == ["reading-audio/1/huerfano.webm"] and dry.deleted == 0 and fake_storage.deleted == []
    assert dry.scanned == 3  # solo el prefijo de lectura

    done = sweep.sweep(apply=True)
    assert done.deleted == 1 and fake_storage.deleted == ["reading-audio/1/huerfano.webm"]

    # al borrar el estudiante en Colegio Smart (cascade), su audio queda huérfano y se barre
    with db.engine.begin() as c:
        c.execute(delete(db.reading_assessments).where(db.reading_assessments.c.id == assessment_id))
    assert sweep.sweep(apply=True).deleted == 1 and kept in fake_storage.deleted
