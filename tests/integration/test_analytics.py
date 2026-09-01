import bcrypt

from api.deps import create_access_token
from db.models import Clinic, StaffAccount


def _make_clinic_with_doctor(db):
    clinic = Clinic(name="Analytics Test Clinic")
    db.add(clinic)
    db.flush()
    doctor = StaffAccount(
        clinic_id=clinic.id, name="Dr. Analytics", role="doctor", contact="doc@analytics.local",
        password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
    )
    db.add(doctor)
    db.flush()
    db.commit()
    return clinic, doctor


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_daily_analytics_reflects_served_and_no_show_activity(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")

    ids = []
    for contact in ("a@b.com", "b@b.com", "c@b.com"):
        resp = client.post(
            f"/clinics/{clinic.id}/queue/join",
            json={"patient_contact": {"type": "email", "value": contact}, "tier": "standard"},
        )
        ids.append(resp.json()["token_id"])

    # a gets called, no-shows and swaps with b
    call1 = client.post("/staff/queue/call-next", headers=_auth(staff_token)).json()
    assert call1["token_id"] == ids[0]
    client.post(f"/staff/queue/tokens/{ids[0]}/no-show", headers=_auth(staff_token))

    # b (now called) gets served
    client.post(f"/staff/queue/tokens/{ids[1]}/mark-served", headers=_auth(staff_token))

    # a is reinserted right behind b's old slot, so it's next up again (c stays waiting)
    call2 = client.post("/staff/queue/call-next", headers=_auth(staff_token)).json()
    assert call2["token_id"] == ids[0]
    client.post(f"/staff/queue/tokens/{ids[0]}/mark-served", headers=_auth(staff_token))

    response = client.get("/admin/analytics/daily", headers=_auth(staff_token))
    assert response.status_code == 200
    body = response.json()

    assert body["served_count"] == 2
    assert body["no_show_count"] == 1
    assert body["no_show_rate"] == 1 / 2  # 1 no-show out of 2 call-next invocations
    assert body["average_service_seconds"] is not None
    assert body["average_wait_seconds"] is not None


def test_daily_analytics_before_any_activity_returns_nulls_not_errors(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")

    response = client.get("/admin/analytics/daily", headers=_auth(staff_token))

    assert response.status_code == 200
    body = response.json()
    assert body["served_count"] == 0
    assert body["no_show_count"] == 0
    assert body["no_show_rate"] is None
    assert body["average_service_seconds"] is None
    assert body["average_wait_seconds"] is None
