from datetime import date
from unittest.mock import patch

from db.models import Clinic, NotificationLog, QueueSession, StaffAccount, Token
from notifications.result import SendResult
from notifications.service import process_job


def _make_token(db, patient_email=None):
    clinic = Clinic(name="Notify Test Clinic")
    db.add(clinic)
    db.flush()
    doctor = StaffAccount(
        clinic_id=clinic.id, name="Dr. Notify", role="doctor", contact="doc@notify.local", password_hash="x"
    )
    db.add(doctor)
    db.flush()
    session = QueueSession(clinic_id=clinic.id, doctor_id=doctor.id, session_date=date.today())
    db.add(session)
    db.flush()
    token = Token(
        session_id=session.id, patient_contact="telegram:12345", patient_email=patient_email,
        tier="standard", display_number="S-1",
    )
    db.add(token)
    db.commit()
    return token


def _job(token, patient_email=None):
    return {
        "token_id": str(token.id),
        "event": "your_turn",
        "patient_contact": token.patient_contact,
        "patient_email": patient_email if patient_email is not None else token.patient_email,
        "clinic_name": "Notify Test Clinic",
        "display_number": token.display_number,
    }


@patch("notifications.service.time.sleep")
@patch("notifications.service.telegram_client.send")
def test_telegram_success_on_first_attempt_logs_once(mock_send, mock_sleep, db):
    token = _make_token(db)
    mock_send.return_value = SendResult(ok=True)

    process_job(db, _job(token))

    logs = db.query(NotificationLog).filter_by(token_id=token.id).all()
    assert len(logs) == 1
    assert logs[0].channel == "telegram"
    assert logs[0].status == "sent"
    assert logs[0].attempt_count == 1
    mock_sleep.assert_not_called()


@patch("notifications.service.time.sleep")
@patch("notifications.service.email_client.send")
@patch("notifications.service.telegram_client.send")
def test_telegram_exhausted_falls_back_to_email(mock_telegram, mock_email, mock_sleep, db):
    token = _make_token(db, patient_email="patient@example.com")
    mock_telegram.return_value = SendResult(ok=False, error="bot blocked")
    mock_email.return_value = SendResult(ok=True)

    process_job(db, _job(token))

    assert mock_telegram.call_count == 3
    mock_email.assert_called_once()
    assert mock_sleep.call_count == 2  # backoff between attempts 1->2 and 2->3, none after the last

    logs = {log.channel: log for log in db.query(NotificationLog).filter_by(token_id=token.id).all()}
    assert logs["telegram"].status == "failed"
    assert logs["telegram"].attempt_count == 3
    assert logs["email"].status == "sent"
    assert logs["email"].attempt_count == 1


@patch("notifications.service.time.sleep")
@patch("notifications.service.email_client.send")
@patch("notifications.service.telegram_client.send")
def test_both_channels_fail_are_both_logged_as_failed(mock_telegram, mock_email, mock_sleep, db):
    token = _make_token(db, patient_email="patient@example.com")
    mock_telegram.return_value = SendResult(ok=False, error="bot blocked")
    mock_email.return_value = SendResult(ok=False, error="smtp down")

    process_job(db, _job(token))

    logs = {log.channel: log for log in db.query(NotificationLog).filter_by(token_id=token.id).all()}
    assert logs["telegram"].status == "failed"
    assert logs["email"].status == "failed"
    assert logs["email"].last_error == "smtp down"


@patch("notifications.service.time.sleep")
@patch("notifications.service.email_client.send")
@patch("notifications.service.telegram_client.send")
def test_no_email_on_file_skips_fallback_entirely(mock_telegram, mock_email, mock_sleep, db):
    token = _make_token(db, patient_email=None)
    mock_telegram.return_value = SendResult(ok=False, error="bot blocked")

    process_job(db, _job(token))

    mock_email.assert_not_called()
    logs = db.query(NotificationLog).filter_by(token_id=token.id).all()
    assert len(logs) == 1
    assert logs[0].channel == "telegram"
    assert logs[0].status == "failed"
