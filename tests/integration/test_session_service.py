from datetime import date, datetime, timezone
from unittest.mock import patch

from core.session_service import get_or_create_active_session
from db.models import Clinic, StaffAccount


def _make_clinic_with_doctor(db, tz_name: str):
    clinic = Clinic(name=f"Timezone Test Clinic ({tz_name})", timezone=tz_name)
    db.add(clinic)
    db.flush()
    doctor = StaffAccount(
        clinic_id=clinic.id, name="Dr. Timezone", role="doctor",
        contact=f"doc@{tz_name.replace('/', '-').lower()}.test", password_hash="x",
    )
    db.add(doctor)
    db.commit()
    return clinic


def _frozen_today_in(moment: datetime):
    def _today_in(tz_name):
        from core.clock import today_in as real_today_in
        return real_today_in(tz_name, now=moment)
    return _today_in


def test_session_date_uses_the_clinics_own_timezone_not_utc(db):
    """23:30 UTC on the 1st is already 05:00 on the 2nd in Asia/Kolkata -- the session
    created at that instant should be dated the 2nd, not the 1st."""
    clinic = _make_clinic_with_doctor(db, "Asia/Kolkata")
    moment = datetime(2026, 9, 1, 23, 30, tzinfo=timezone.utc)

    with patch("core.session_service.today_in", side_effect=_frozen_today_in(moment)):
        session = get_or_create_active_session(db, clinic.id)

    assert session.session_date == date(2026, 9, 2)


def test_two_clinics_in_different_timezones_can_disagree_on_todays_date(db):
    kolkata_clinic = _make_clinic_with_doctor(db, "Asia/Kolkata")
    ny_clinic = _make_clinic_with_doctor(db, "America/New_York")
    moment = datetime(2026, 9, 2, 1, 0, tzinfo=timezone.utc)

    with patch("core.session_service.today_in", side_effect=_frozen_today_in(moment)):
        kolkata_session = get_or_create_active_session(db, kolkata_clinic.id)
        ny_session = get_or_create_active_session(db, ny_clinic.id)

    assert kolkata_session.session_date == date(2026, 9, 2)
    assert ny_session.session_date == date(2026, 9, 1)
