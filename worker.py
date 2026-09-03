"""Notification-consumer process entrypoint — deliberately separate from main.py so a slow
Telegram/SMTP call can never tie up an API worker thread (queueflow-lld.md §1)."""

import logging
import signal
import threading
import time

import redis

from db.session import SessionLocal
from notifications.service import dequeue_notification, process_job

logger = logging.getLogger(__name__)

_running = True


def _handle_shutdown(signum, frame):
    global _running
    _running = False


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # signal.signal() only works from a process's main thread -- raises ValueError
    # otherwise. When run as a background thread inside the API process (see
    # RUN_BACKGROUND_WORKERS_IN_PROCESS in config.py), this is skipped: the daemon
    # thread just gets torn down when the main process exits, no graceful drain.
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _handle_shutdown)
        signal.signal(signal.SIGINT, _handle_shutdown)

    logger.info("Notification worker started")
    while _running:
        try:
            job = dequeue_notification(timeout_seconds=5)
        except redis.RedisError:
            logger.exception("Redis unreachable, retrying shortly")
            time.sleep(2)
            continue

        if job is None:
            continue

        db = SessionLocal()
        try:
            process_job(db, job)
        except Exception:
            logger.exception("Failed to process notification job for token %s", job.get("token_id"))
        finally:
            db.close()

    logger.info("Notification worker shutting down")


if __name__ == "__main__":
    main()
