import uuid
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import ServiceTimeSample

DEFAULT_ESTIMATE_SECONDS = 600
ROLLING_WINDOW = 10


def estimated_wait_seconds(db: Session, session_id: uuid.UUID, position: int) -> int:
    samples = db.execute(
        select(ServiceTimeSample.duration_seconds)
        .where(ServiceTimeSample.session_id == session_id)
        .order_by(ServiceTimeSample.recorded_at.desc())
        .limit(ROLLING_WINDOW)
    ).scalars().all()

    avg = mean(samples) if samples else DEFAULT_ESTIMATE_SECONDS
    return int(position * avg)
