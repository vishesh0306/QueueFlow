"""GET /staff/queue must show the waiting list in true predicted call order (what
call_next() would actually do), not raw join order -- a late-arriving priority patient
should appear wherever the interleave would actually call them, and a no-show swap's
reinserted patient should appear right where they were placed, not at the back."""
import bcrypt

from api.deps import create_access_token
from db.models import Clinic, StaffAccount


def _make_clinic_with_doctor(db, ratio="2:1"):
    clinic = Clinic(name="Ordering Test Clinic", standard_priority_ratio=ratio)
    db.add(clinic)
    db.flush()
    doctor = StaffAccount(
        clinic_id=clinic.id, name="Dr. Ordering", role="doctor", contact="doc@ordering.test",
        password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
    )
    db.add(doctor)
    db.flush()
    db.commit()
    return clinic, doctor


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _join(client, clinic_id, contact, tier="standard"):
    resp = client.post(
        f"/clinics/{clinic_id}/queue/join",
        json={"patient_contact": {"type": "email", "value": contact}, "tier": tier},
    )
    return resp.json()["token_id"]


def test_late_priority_arrival_shown_at_its_true_call_position(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")

    s_ids = [_join(client, clinic.id, f"s{i}@test.com", "standard") for i in range(1, 5)]
    p1_id = _join(client, clinic.id, "p1@test.com", "priority")

    # call_counter is still 0 (nobody's been called yet) -> priority is due immediately,
    # so P1 should show FIRST despite joining last.
    queue = client.get("/staff/queue", headers=_auth(staff_token)).json()
    waiting_ids = [t["token_id"] for t in queue["waiting"]]

    assert waiting_ids == [p1_id, s_ids[0], s_ids[1], s_ids[2], s_ids[3]]


def test_order_shifts_correctly_as_the_call_counter_advances(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")

    s_ids = [_join(client, clinic.id, f"s{i}@test.com", "standard") for i in range(1, 5)]
    p1_id = _join(client, clinic.id, "p1@test.com", "priority")

    # Call once (consumes the counter=0 slot, which was priority) -- P1 is called.
    called = client.post("/staff/queue/call-next", headers=_auth(staff_token)).json()
    assert called["token_id"] == p1_id

    # Now counter=1 (standard's turn): remaining waiting order should be pure standard FIFO.
    queue = client.get("/staff/queue", headers=_auth(staff_token)).json()
    waiting_ids = [t["token_id"] for t in queue["waiting"]]
    assert waiting_ids == s_ids


def test_no_show_swap_reinsertion_shown_at_correct_position(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")

    a_id = _join(client, clinic.id, "a@test.com", "standard")
    b_id = _join(client, clinic.id, "b@test.com", "standard")
    c_id = _join(client, clinic.id, "c@test.com", "standard")

    call_resp = client.post("/staff/queue/call-next", headers=_auth(staff_token)).json()
    assert call_resp["token_id"] == a_id  # counter=0 is priority's slot, but none exist -> falls back to standard, a is first

    no_show_resp = client.post(f"/staff/queue/tokens/{a_id}/no-show", headers=_auth(staff_token))
    assert no_show_resp.json()["action"] == "swapped"  # a<->b swap; a reinserted right behind b's old slot

    queue = client.get("/staff/queue", headers=_auth(staff_token)).json()
    waiting_ids = [t["token_id"] for t in queue["waiting"]]

    # a should be shown ahead of c, reflecting the swap's reinsertion point -- not at
    # the back, and not just wherever raw join order would have put it.
    assert waiting_ids == [a_id, c_id]


def test_emergency_override_shown_first_in_waiting_list(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")

    s1_id = _join(client, clinic.id, "s1@test.com", "standard")
    emergency_resp = client.post(
        "/staff/queue/emergency-override", headers=_auth(staff_token),
        json={"patient_contact": {"type": "email", "value": "urgent@test.com"}},
    )
    emergency_id = emergency_resp.json()["token_id"]

    queue = client.get("/staff/queue", headers=_auth(staff_token)).json()
    waiting_ids = [t["token_id"] for t in queue["waiting"]]

    assert waiting_ids == [emergency_id, s1_id]
