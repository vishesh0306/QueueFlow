import bcrypt

from api.deps import create_access_token
from db.models import Clinic, StaffAccount


def _make_clinic_with_doctor(db):
    clinic = Clinic(name="E2E Clinic", priority_fee_paise=20000)
    db.add(clinic)
    db.flush()
    doctor = StaffAccount(
        clinic_id=clinic.id, name="Dr. E2E", role="doctor", contact="doc@e2e.local",
        password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
    )
    db.add(doctor)
    db.flush()
    db.commit()
    return clinic, doctor


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_staff_queue_list_reflects_called_and_waiting_tokens(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")

    ids = []
    for contact in ("a@b.com", "b@b.com"):
        resp = client.post(
            f"/clinics/{clinic.id}/queue/join",
            json={"patient_contact": {"type": "email", "value": contact}, "tier": "standard"},
        )
        ids.append(resp.json()["token_id"])

    client.post("/staff/queue/call-next", headers=_auth(staff_token))

    queue = client.get("/staff/queue", headers=_auth(staff_token)).json()
    assert queue["session_status"] == "active"
    assert [t["token_id"] for t in queue["called"]] == [ids[0]]
    assert [t["token_id"] for t in queue["waiting"]] == [ids[1]]


def test_join_rejects_a_duplicate_active_booking(client, db):
    clinic, _doctor = _make_clinic_with_doctor(db)
    body = {"patient_contact": {"type": "email", "value": "dup@test.com"}, "tier": "standard"}

    first = client.post(f"/clinics/{clinic.id}/queue/join", json=body)
    assert first.status_code == 201

    second = client.post(f"/clinics/{clinic.id}/queue/join", json=body)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ALREADY_IN_QUEUE"


def test_call_next_returns_queue_paused_when_paused(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")
    client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}, "tier": "standard"},
    )

    pause_resp = client.post("/staff/queue/pause", headers=_auth(staff_token))
    assert pause_resp.json()["status"] == "paused"

    call_resp = client.post("/staff/queue/call-next", headers=_auth(staff_token))
    assert call_resp.status_code == 409
    assert call_resp.json()["error"]["code"] == "QUEUE_PAUSED"

    resume_resp = client.post("/staff/queue/resume", headers=_auth(staff_token))
    assert resume_resp.json()["status"] == "active"

    call_resp_after_resume = client.post("/staff/queue/call-next", headers=_auth(staff_token))
    assert call_resp_after_resume.status_code == 200


def test_patient_join_then_staff_calls_and_serves(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")

    join_resp = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "telegram", "value": "123"}, "tier": "standard"},
    )
    assert join_resp.status_code == 201
    join_body = join_resp.json()
    assert join_body["position"] == 1
    token_id = join_body["token_id"]

    status_resp = client.get(f"/queue/tokens/{token_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "waiting"

    call_resp = client.post("/staff/queue/call-next", headers=_auth(staff_token))
    assert call_resp.status_code == 200
    assert call_resp.json()["token_id"] == token_id

    served_resp = client.post(f"/staff/queue/tokens/{token_id}/mark-served", headers=_auth(staff_token))
    assert served_resp.status_code == 200
    assert served_resp.json()["status"] == "served"

    final_status = client.get(f"/queue/tokens/{token_id}/status")
    assert final_status.json()["status"] == "served"


def test_patient_can_cancel_own_waiting_token(client, db):
    clinic, _doctor = _make_clinic_with_doctor(db)

    join_resp = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}, "tier": "standard"},
    )
    token_id = join_resp.json()["token_id"]

    cancel_resp = client.delete(f"/queue/tokens/{token_id}")
    assert cancel_resp.status_code == 204

    status_resp = client.get(f"/queue/tokens/{token_id}/status")
    assert status_resp.json()["status"] == "cancelled"


def test_call_next_on_empty_queue_returns_queue_empty_error(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")

    response = client.post("/staff/queue/call-next", headers=_auth(staff_token))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "QUEUE_EMPTY"


def test_mark_paid_rejects_a_negative_fee_amount(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")
    join_resp = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}, "tier": "standard"},
    )
    token_id = join_resp.json()["token_id"]
    client.post("/staff/queue/call-next", headers=_auth(staff_token))

    resp = client.post(
        f"/staff/queue/tokens/{token_id}/mark-paid",
        json={"fee_amount_paise": -100},
        headers=_auth(staff_token),
    )
    assert resp.status_code == 422


def test_mark_paid_rejects_a_cancelled_token(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")
    join_resp = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}, "tier": "standard"},
    )
    token_id = join_resp.json()["token_id"]
    client.delete(f"/queue/tokens/{token_id}")

    resp = client.post(
        f"/staff/queue/tokens/{token_id}/mark-paid",
        json={"fee_amount_paise": 20000},
        headers=_auth(staff_token),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INVALID_TRANSITION"


def test_close_blocks_new_joins_but_call_next_keeps_working(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")
    join_resp = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}, "tier": "standard"},
    )
    assert join_resp.status_code == 201

    close_resp = client.post("/staff/queue/close", headers=_auth(staff_token))
    assert close_resp.status_code == 200
    assert close_resp.json()["status"] == "closed"

    late_join = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "late@b.com"}, "tier": "standard"},
    )
    assert late_join.status_code == 409
    assert late_join.json()["error"]["code"] == "SESSION_CLOSED"

    call_resp = client.post("/staff/queue/call-next", headers=_auth(staff_token))
    assert call_resp.status_code == 200

    reopen_resp = client.post("/staff/queue/resume", headers=_auth(staff_token))
    assert reopen_resp.status_code == 200
    assert reopen_resp.json()["status"] == "active"

    rejoin = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "late@b.com"}, "tier": "standard"},
    )
    assert rejoin.status_code == 201


def test_emergency_token_loses_priority_after_two_no_shows_via_api(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")

    override_resp = client.post(
        "/staff/queue/emergency-override",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}},
        headers=_auth(staff_token),
    )
    token_id = override_resp.json()["token_id"]

    client.post("/staff/queue/call-next", headers=_auth(staff_token))
    client.post(f"/staff/queue/tokens/{token_id}/no-show", headers=_auth(staff_token))
    client.post("/staff/queue/call-next", headers=_auth(staff_token))
    client.post(f"/staff/queue/tokens/{token_id}/no-show", headers=_auth(staff_token))

    queue = client.get("/staff/queue", headers=_auth(staff_token)).json()
    matching = [t for t in queue["waiting"] if t["token_id"] == token_id]
    assert len(matching) == 1
    assert matching[0]["emergency_override"] is False


def test_staff_can_fix_a_mistyped_contact(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")
    join_resp = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "telegram", "value": "1234"}, "tier": "standard"},
    )
    token_id = join_resp.json()["token_id"]

    resp = client.post(
        f"/staff/queue/tokens/{token_id}/update-contact",
        json={"patient_contact": {"type": "telegram", "value": "12345"}},
        headers=_auth(staff_token),
    )
    assert resp.status_code == 200
    assert resp.json()["patient_contact"] == "telegram:12345"


def test_update_contact_rejects_a_collision_with_another_active_token(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")
    client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}, "tier": "standard"},
    )
    join_b = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "b@b.com"}, "tier": "standard"},
    )
    token_b = join_b.json()["token_id"]

    resp = client.post(
        f"/staff/queue/tokens/{token_b}/update-contact",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}},
        headers=_auth(staff_token),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ALREADY_IN_QUEUE"


def test_staff_can_change_a_waiting_tokens_tier(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")
    join_resp = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}, "tier": "standard"},
    )
    token_id = join_resp.json()["token_id"]

    resp = client.post(
        f"/staff/queue/tokens/{token_id}/change-tier",
        json={"tier": "priority"},
        headers=_auth(staff_token),
    )
    assert resp.status_code == 200
    assert resp.json()["tier"] == "priority"


def test_patient_can_self_upgrade_to_priority(client, db):
    clinic, _doctor = _make_clinic_with_doctor(db)
    join_resp = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}, "tier": "standard"},
    )
    token_id = join_resp.json()["token_id"]

    resp = client.post(f"/queue/tokens/{token_id}/upgrade-to-priority")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "priority"
    assert body["fee_due_paise"] == clinic.priority_fee_paise

    status_resp = client.get(f"/queue/tokens/{token_id}/status")
    assert status_resp.json()["tier"] == "priority"


def test_patient_cannot_self_upgrade_a_token_already_at_priority(client, db):
    clinic, _doctor = _make_clinic_with_doctor(db)
    join_resp = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}, "tier": "priority"},
    )
    token_id = join_resp.json()["token_id"]

    resp = client.post(f"/queue/tokens/{token_id}/upgrade-to-priority")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INVALID_TRANSITION"


def test_emergency_override_on_an_already_queued_patient_does_not_orphan_their_token(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")
    join_resp = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}, "tier": "standard"},
    )
    token_id = join_resp.json()["token_id"]

    override_resp = client.post(
        "/staff/queue/emergency-override",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}},
        headers=_auth(staff_token),
    )
    assert override_resp.status_code == 201
    assert override_resp.json()["token_id"] == token_id

    queue = client.get("/staff/queue", headers=_auth(staff_token)).json()
    matching = [t for t in queue["waiting"] if t["patient_contact"] == "email:a@b.com"]
    assert len(matching) == 1
    assert matching[0]["emergency_override"] is True


def test_served_today_reports_paid_and_pending_patients(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")

    # Priority patient: served and paid.
    join_a = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "paid@b.com"}, "tier": "priority"},
    )
    token_a = join_a.json()["token_id"]
    client.post("/staff/queue/call-next", headers=_auth(staff_token))
    client.post(
        f"/staff/queue/tokens/{token_a}/mark-paid",
        json={"fee_amount_paise": clinic.priority_fee_paise},
        headers=_auth(staff_token),
    )
    client.post(f"/staff/queue/tokens/{token_a}/mark-served", headers=_auth(staff_token))

    # Priority patient: served but never marked paid -- should count as pending at the
    # clinic's priority fee, not as free.
    join_b = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "unpaid@b.com"}, "tier": "priority"},
    )
    token_b = join_b.json()["token_id"]
    client.post("/staff/queue/call-next", headers=_auth(staff_token))
    client.post(f"/staff/queue/tokens/{token_b}/mark-served", headers=_auth(staff_token))

    # Standard patient: served, free -- should not appear in pending at all.
    join_c = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "free@b.com"}, "tier": "standard"},
    )
    token_c = join_c.json()["token_id"]
    client.post("/staff/queue/call-next", headers=_auth(staff_token))
    client.post(f"/staff/queue/tokens/{token_c}/mark-served", headers=_auth(staff_token))

    resp = client.get("/staff/queue/served-today", headers=_auth(staff_token))
    assert resp.status_code == 200
    body = resp.json()

    served_by_id = {s["token_id"]: s for s in body["served"]}
    assert len(served_by_id) == 3
    assert served_by_id[token_a]["paid"] is True
    assert served_by_id[token_a]["fee_amount_paise"] == clinic.priority_fee_paise
    assert served_by_id[token_b]["paid"] is False
    assert served_by_id[token_b]["fee_amount_paise"] == clinic.priority_fee_paise
    assert served_by_id[token_c]["paid"] is False
    assert served_by_id[token_c]["fee_amount_paise"] == 0

    assert body["total_collected_paise"] == clinic.priority_fee_paise
    assert body["total_pending_paise"] == clinic.priority_fee_paise  # only token_b -- token_c is free


def test_served_today_excludes_waiting_and_called_tokens(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")
    client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}, "tier": "standard"},
    )
    client.post("/staff/queue/call-next", headers=_auth(staff_token))

    resp = client.get("/staff/queue/served-today", headers=_auth(staff_token))
    assert resp.json()["served"] == []


def test_staff_can_void_a_payment(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")
    join_resp = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}, "tier": "standard"},
    )
    token_id = join_resp.json()["token_id"]
    client.post("/staff/queue/call-next", headers=_auth(staff_token))
    client.post(
        f"/staff/queue/tokens/{token_id}/mark-paid",
        json={"fee_amount_paise": 20000},
        headers=_auth(staff_token),
    )

    queue_before = client.get("/staff/queue", headers=_auth(staff_token)).json()
    assert queue_before["called"][0]["paid"] is True
    assert queue_before["called"][0]["fee_amount_paise"] == 20000

    void_resp = client.post(f"/staff/queue/tokens/{token_id}/void-payment", headers=_auth(staff_token))
    assert void_resp.status_code == 200
    assert void_resp.json()["paid"] is False

    queue = client.get("/staff/queue", headers=_auth(staff_token)).json()
    assert queue["called"][0]["paid"] is False


def test_void_payment_rejects_a_token_with_no_payment(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")
    join_resp = client.post(
        f"/clinics/{clinic.id}/queue/join",
        json={"patient_contact": {"type": "email", "value": "a@b.com"}, "tier": "standard"},
    )
    token_id = join_resp.json()["token_id"]

    resp = client.post(f"/staff/queue/tokens/{token_id}/void-payment", headers=_auth(staff_token))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INVALID_TRANSITION"


def test_no_show_swap_via_api(client, db):
    clinic, doctor = _make_clinic_with_doctor(db)
    staff_token = create_access_token(doctor.id, clinic.id, "doctor")

    ids = []
    for contact in ("a@b.com", "b@b.com"):
        resp = client.post(
            f"/clinics/{clinic.id}/queue/join",
            json={"patient_contact": {"type": "email", "value": contact}, "tier": "standard"},
        )
        ids.append(resp.json()["token_id"])

    called = client.post("/staff/queue/call-next", headers=_auth(staff_token)).json()
    assert called["token_id"] == ids[0]

    no_show_resp = client.post(f"/staff/queue/tokens/{ids[0]}/no-show", headers=_auth(staff_token))
    assert no_show_resp.status_code == 200
    body = no_show_resp.json()
    assert body["action"] == "swapped"
    assert body["new_called_token_id"] == ids[1]
