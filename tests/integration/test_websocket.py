import bcrypt

from api.deps import create_access_token
from db.models import Clinic, StaffAccount


def _make_clinic_with_doctor(db):
    clinic = Clinic(name="WS Test Clinic")
    db.add(clinic)
    db.flush()
    doctor = StaffAccount(
        clinic_id=clinic.id, name="Dr. WS", role="doctor", contact="doc@ws.local",
        password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
    )
    db.add(doctor)
    db.flush()
    db.commit()
    return clinic, doctor


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _join(client, clinic_id, contact):
    resp = client.post(
        f"/clinics/{clinic_id}/queue/join",
        json={"patient_contact": {"type": "email", "value": contact}, "tier": "standard"},
    )
    return resp.json()["token_id"]


def test_join_broadcasts_to_connected_clinic_channel(client, db):
    clinic, _doctor = _make_clinic_with_doctor(db)

    with client.websocket_connect(f"/ws/queue/{clinic.id}") as ws:
        join_resp = client.post(
            f"/clinics/{clinic.id}/queue/join",
            json={"patient_contact": {"type": "email", "value": "a@b.com"}, "tier": "standard"},
        )
        assert join_resp.status_code == 201

        message = ws.receive_json()
        assert message["event"] == "queue_updated"
        assert message["session_id"]


def test_personalized_position_updates_for_own_token(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")

    first_id = _join(client, clinic.id, "a@b.com")
    second_id = _join(client, clinic.id, "b@b.com")

    with client.websocket_connect(f"/ws/queue/{clinic.id}?token_id={second_id}") as ws:
        call_resp = client.post("/staff/queue/call-next", headers=_auth(staff_token))
        assert call_resp.status_code == 200
        assert call_resp.json()["token_id"] == first_id

        message = ws.receive_json()
        assert message["event"] == "queue_updated"
        assert message["your_token_id"] == second_id
        assert message["status"] == "waiting"
        assert message["position"] == 1  # moved up now that the first patient's been called


def test_unrelated_connection_gets_bare_event_only(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")
    _join(client, clinic.id, "a@b.com")

    with client.websocket_connect(f"/ws/queue/{clinic.id}") as ws:  # no token_id -> staff/board view
        client.post("/staff/queue/call-next", headers=_auth(staff_token))

        message = ws.receive_json()
        assert message["event"] == "queue_updated"
        assert "your_token_id" not in message


def test_no_show_swap_broadcasts_updated_status(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")

    first_id = _join(client, clinic.id, "a@b.com")
    second_id = _join(client, clinic.id, "b@b.com")

    client.post("/staff/queue/call-next", headers=_auth(staff_token))  # calls first patient

    with client.websocket_connect(f"/ws/queue/{clinic.id}?token_id={second_id}") as ws:
        no_show_resp = client.post(f"/staff/queue/tokens/{first_id}/no-show", headers=_auth(staff_token))
        assert no_show_resp.status_code == 200

        message = ws.receive_json()
        assert message["your_token_id"] == second_id
        assert message["status"] == "called"  # swapped in, now called
        assert message["position"] is None


def test_walk_in_broadcasts_to_connected_clinic_channel(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")

    with client.websocket_connect(f"/ws/queue/{clinic.id}") as ws:
        resp = client.post(
            "/staff/queue/walk-in",
            json={"patient_contact": {"type": "email", "value": "walkin@b.com"}, "tier": "standard"},
            headers=_auth(staff_token),
        )
        assert resp.status_code == 201

        message = ws.receive_json()
        assert message["event"] == "queue_updated"


def test_pause_and_resume_broadcast_live_to_a_waiting_patient(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")
    token_id = _join(client, clinic.id, "a@b.com")

    with client.websocket_connect(f"/ws/queue/{clinic.id}?token_id={token_id}") as ws:
        pause_resp = client.post("/staff/queue/pause", headers=_auth(staff_token))
        assert pause_resp.status_code == 200

        message = ws.receive_json()
        assert message["session_status"] == "paused"
        assert message["your_token_id"] == token_id  # still personalized, patient didn't lose their place
        assert message["status"] == "waiting"

        resume_resp = client.post("/staff/queue/resume", headers=_auth(staff_token))
        assert resume_resp.status_code == 200

        message = ws.receive_json()
        assert message["session_status"] == "active"
