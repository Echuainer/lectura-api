"""Deletes reading audio in R2 that no assessment references any more.

Orphans appear when Colegio Smart deletes a student (ON DELETE CASCADE removes their readings, not their objects)
or when a discard/import fails halfway. Objects younger than `min_age_hours` are kept: a draft may be uploading.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import db, storage

PREFIX = "reading-audio/"


@dataclass
class SweepResult:
    scanned: int
    orphans: list[str]
    deleted: int


def sweep(min_age_hours: float = 24, apply: bool = False) -> SweepResult:
    with db.engine.connect() as conn:
        referenced = {k for (k,) in conn.execute(select(db.reading_assessments.c.audio_key).where(
            db.reading_assessments.c.audio_key.is_not(None)))}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=min_age_hours)
    objects = storage.list_keys(PREFIX)
    orphans = [k for k, modified in objects if k not in referenced and modified < cutoff]
    deleted = 0
    if apply:
        for key in orphans:
            storage.delete(key)
            deleted += 1
    return SweepResult(scanned=len(objects), orphans=orphans, deleted=deleted)
