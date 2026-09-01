import smtplib
from email.message import EmailMessage

from config import settings
from notifications.result import SendResult


def send(patient_email: str, message: str) -> SendResult:
    email = EmailMessage()
    email["Subject"] = "QueueFlow update"
    email["From"] = settings.smtp_from_address
    email["To"] = patient_email
    email.set_content(message)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_username:
                smtp.starttls()
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(email)
        return SendResult(ok=True)
    except (smtplib.SMTPException, OSError) as exc:
        return SendResult(ok=False, error=str(exc))
