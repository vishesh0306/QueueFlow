"""Telegram inbound-message poller.

A patient has no way to know their own numeric Telegram chat_id, and typing it in
manually (the old join-form behavior) was a dead end for anyone but a developer
testing with the Bot API directly. This process resolves it automatically instead:
a patient taps a /start deep link (see GET /clinics/{id}/telegram-connect), Telegram
sends us a message carrying both their chat_id and the clinic_id we encoded as the
link's payload, and we reply with a join link that already has the chat_id filled in.

Separate process from worker.py -- that one only sends notifications, this one only
receives inbound bot messages. Uses long-polling against getUpdates rather than a
webhook, since a webhook needs a public HTTPS endpoint most local/pilot deployments
won't have.
"""
import logging
import signal
import time
import uuid

import requests

from config import settings
from db.models import Clinic
from db.session import SessionLocal

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"
_running = True


def _handle_shutdown(signum, frame):
    global _running
    _running = False


def _reply(chat_id: int, text: str) -> None:
    try:
        requests.post(
            f"{_API_BASE}/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except requests.RequestException:
        logger.exception("Failed to reply to chat %s", chat_id)


def _handle_start(chat_id: int, payload: str) -> None:
    try:
        clinic_id = uuid.UUID(payload)
    except ValueError:
        _reply(chat_id, "This link doesn't look right — please use the link or QR code from the clinic's join page.")
        return

    db = SessionLocal()
    try:
        clinic = db.get(Clinic, clinic_id)
    finally:
        db.close()

    if clinic is None:
        _reply(chat_id, "This link doesn't look right — please use the link or QR code from the clinic's join page.")
        return

    join_link = f"{settings.public_base_url}/patient-app/?clinic={clinic_id}&telegram_id={chat_id}"
    _reply(
        chat_id,
        f"Welcome to {clinic.name}! Tap this link to join the queue — your Telegram is already connected:\n{join_link}",
    )


_LONG_POLL_SECONDS = 20


def _poll_once(offset: int | None) -> int | None:
    """Fetches and handles one batch of updates, returning the next offset to use."""
    params = {"timeout": _LONG_POLL_SECONDS}
    if offset is not None:
        params["offset"] = offset

    # The client-side timeout needs real headroom over the server-side long-poll
    # window above -- Telegram can legitimately hold the connection open for close
    # to the full 20s before responding, and network latency eats into that further.
    response = requests.get(
        f"{_API_BASE}/bot{settings.telegram_bot_token}/getUpdates", params=params, timeout=_LONG_POLL_SECONDS + 15,
    )
    response.raise_for_status()
    updates = response.json().get("result", [])

    for update in updates:
        offset = update["update_id"] + 1
        message = update.get("message") or {}
        text = message.get("text", "")
        chat_id = message.get("chat", {}).get("id")
        if chat_id is None or not text.startswith("/start"):
            continue

        parts = text.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else ""
        if not payload:
            _reply(chat_id, "Hi! To join a clinic's queue, use the Telegram link or QR code from that clinic.")
            continue

        _handle_start(chat_id, payload)

    return offset


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    if not settings.telegram_bot_token:
        logger.info("No TELEGRAM_BOT_TOKEN configured -- telegram_bot poller exiting immediately.")
        return

    logger.info("Telegram bot poller started")
    offset = None
    while _running:
        try:
            offset = _poll_once(offset)
        except requests.exceptions.Timeout:
            # An occasional long-poll timing out is normal network reality, not a bug
            # worth a full traceback -- just retry.
            logger.warning("Telegram getUpdates timed out, retrying")
        except requests.RequestException:
            logger.exception("Telegram getUpdates failed, retrying shortly")
            time.sleep(5)

    logger.info("Telegram bot poller shutting down")


if __name__ == "__main__":
    main()
