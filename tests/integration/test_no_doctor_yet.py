"""A freshly signed-up clinic has an admin but no doctor yet (signup only creates one
account). Every queue-control route needs today's session, which needs a doctor to
exist -- this used to crash with an unhandled 500 the moment such a dashboard loaded."""


def _signed_up_admin_headers(client):
    response = client.post(
        "/staff/signup",
        json={
            "clinic_name": "Doctorless Clinic",
            "admin_name": "Just An Admin",
            "admin_contact": "no_doctor_admin@test.com",
            "admin_password": "x",
        },
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_list_queue_returns_clean_409_with_no_doctor(client, db):
    headers = _signed_up_admin_headers(client)

    response = client.get("/staff/queue", headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_DOCTOR_CONFIGURED"


def test_call_next_returns_clean_409_with_no_doctor(client, db):
    headers = _signed_up_admin_headers(client)

    response = client.post("/staff/queue/call-next", headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_DOCTOR_CONFIGURED"


def test_pause_returns_clean_409_with_no_doctor(client, db):
    headers = _signed_up_admin_headers(client)

    response = client.post("/staff/queue/pause", headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_DOCTOR_CONFIGURED"


def test_everything_works_once_a_doctor_is_added(client, db):
    headers = _signed_up_admin_headers(client)

    create_doctor = client.post(
        "/admin/staff",
        headers=headers,
        json={"name": "Dr. Added Later", "role": "doctor", "contact": "added_doctor@test.com", "password": "x"},
    )
    assert create_doctor.status_code == 201

    response = client.get("/staff/queue", headers=headers)

    assert response.status_code == 200
    assert response.json()["session_status"] == "active"
