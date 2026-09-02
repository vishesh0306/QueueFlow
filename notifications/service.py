import json
import logging
import time
import uuid

import redis
from sqlalchemy.orm import Session

from config import settings
from core.clock import utcnow
from db.models import NotificationLog
from notifications import email_client, telegram_client
from notifications.retry import backoff_seconds

logger = logging.getLogger(__name__)

QUEUE_KEY = "queueflow:notifications"
MAX_TELEGRAM_ATTEMPTS = 3

# socket_timeout must exceed the largest BLPOP timeout we'll ever pass to dequeue_notification,
# otherwise the client's own socket read can race BLPOP's server-side timeout and raise instead
# of returning nil — redis-py surfaces that race as redis.exceptions.TimeoutError.
_redis_client = redis.Redis.from_url(settings.redis_url, socket_timeout=30)


def enqueue_notification(job: dict) -> None:
    """Called by the queue engine after a state change commits. Never raises — a failed
    enqueue shouldn't roll back an already-durable queue transition, just loses the ping."""
    try:
        _redis_client.rpush(QUEUE_KEY, json.dumps(job))
    except redis.RedisError:
        logger.warning("Failed to enqueue notification job for token %s", job.get("token_id"), exc_info=True)


def dequeue_notification(timeout_seconds: int = 5) -> dict | None:
    """Blocking pop used by worker.py's consume loop. Returns None on timeout (lets the
    worker loop check for shutdown signals periodically instead of blocking forever)."""
    try:
        result = _redis_client.blpop(QUEUE_KEY, timeout=timeout_seconds)
    except redis.exceptions.TimeoutError:
        # An idle BLPOP wait timing out is expected, routine behavior, not a failure —
        # treat it the same as the empty-result case below.
        return None
    if result is None:
        return None
    _, raw = result
    return json.loads(raw)


def render_message(job: dict) -> str:
    label = job.get("display_number") or job["token_id"]
    return f"{job['clinic_name']}: it's your turn now! (token {label})"


def _create_log(db: Session, token_id: uuid.UUID, channel: str) -> NotificationLog:
    log = NotificationLog(token_id=token_id, channel=channel, status="queued")
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def _send_email(db: Session, job: dict, message: str, address: str) -> None:
    email_log = _create_log(db, job["token_id"], channel="email")
    result = email_client.send(address, message)
    email_log.status = "sent" if result.ok else "failed"
    email_log.attempt_count = 1
    email_log.sent_at = utcnow() if result.ok else None
    email_log.last_error = None if result.ok else result.error
    db.commit()
    if result.ok:
        logger.info("Email sent for token %s", job["token_id"])
    else:
        logger.warning("Email failed for token %s: %s", job["token_id"], result.error)


def process_job(db: Session, job: dict) -> None:
    message = render_message(job)
    patient_contact = job["patient_contact"]

    # The patient chose email as their contact channel -- go straight there, using
    # their own contact value. Trying Telegram first (and failing 3 times, with
    # backoff) against a contact that was never a Telegram ID would just waste
    # ~6 seconds before reaching a fallback most patients never even provided.
    if patient_contact.startswith("email:"):
        _send_email(db, job, message, patient_contact.removeprefix("email:"))
        return

    log = _create_log(db, job["token_id"], channel="telegram")

    result = None
    for attempt in range(1, MAX_TELEGRAM_ATTEMPTS + 1):
        result = telegram_client.send(patient_contact, message)
        if result.ok:
            log.status = "sent"
            log.attempt_count = attempt
            log.sent_at = utcnow()
            db.commit()
            logger.info("Telegram notification sent for token %s (attempt %d)", job["token_id"], attempt)
            return
        if attempt < MAX_TELEGRAM_ATTEMPTS:
            time.sleep(backoff_seconds(attempt))

    log.status = "failed"
    log.attempt_count = MAX_TELEGRAM_ATTEMPTS
    log.last_error = result.error if result else "unknown error"
    db.commit()
    logger.warning(
        "Telegram delivery exhausted for token %s after %d attempts: %s",
        job["token_id"], MAX_TELEGRAM_ATTEMPTS, log.last_error,
    )

    # Fallback channel — only reached if Telegram truly exhausted its attempts,
    # and only if the patient actually left a separate backup email on file.
    patient_email = job.get("patient_email")
    if not patient_email:
        logger.warning("No email on file for token %s, notification undelivered", job["token_id"])
        return

    _send_email(db, job, message, patient_email)
