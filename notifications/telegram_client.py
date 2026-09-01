import requests

from config import settings
from notifications.result import SendResult

_API_BASE = "https://api.telegram.org"


def send(patient_contact: str, message: str) -> SendResult:
    """patient_contact is expected in the "telegram:<chat_id>" form."""
    if not patient_contact.startswith("telegram:"):
        return SendResult(ok=False, error="patient_contact is not a telegram contact")
    chat_id = patient_contact.removeprefix("telegram:")

    try:
        response = requests.post(
            f"{_API_BASE}/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
    except requests.RequestException as exc:
        return SendResult(ok=False, error=str(exc))

    if response.status_code == 200 and response.json().get("ok"):
        return SendResult(ok=True)
    return SendResult(ok=False, error=response.text)
