def _signup_payload(contact="new_admin@clinic.test"):
    return {
        "clinic_name": "Brand New Clinic",
        "admin_name": "Dr. Founder",
        "admin_contact": contact,
        "admin_password": "correct-password",
    }


def test_signup_creates_clinic_and_returns_a_working_token(client, db):
    response = client.post("/staff/signup", json=_signup_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "admin"
    assert body["clinic_id"]
    assert body["access_token"]

    # The token actually works against an admin-only endpoint.
    config_resp = client.get(
        f"/admin/clinics/{body['clinic_id']}/config",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert config_resp.status_code == 200
    assert config_resp.json()["name"] == "Brand New Clinic"


def test_can_log_in_with_credentials_from_signup(client, db):
    client.post("/staff/signup", json=_signup_payload("login_check@clinic.test"))

    response = client.post(
        "/staff/login", json={"contact": "login_check@clinic.test", "password": "correct-password"}
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_signup_rejects_a_contact_already_in_use(client, db):
    client.post("/staff/signup", json=_signup_payload("taken@clinic.test"))

    second = client.post(
        "/staff/signup",
        json={
            "clinic_name": "A Different Clinic",
            "admin_name": "Someone Else",
            "admin_contact": "taken@clinic.test",
            "admin_password": "whatever",
        },
    )

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "CONTACT_TAKEN"


def test_two_signups_produce_two_independent_clinics(client, db):
    first = client.post("/staff/signup", json=_signup_payload("clinic_a_admin@test.com")).json()
    second = client.post(
        "/staff/signup",
        json={
            "clinic_name": "Second Clinic",
            "admin_name": "Second Admin",
            "admin_contact": "clinic_b_admin@test.com",
            "admin_password": "x",
        },
    ).json()

    assert first["clinic_id"] != second["clinic_id"]

    # The first admin can't see the second clinic's config (cross-clinic RBAC check).
    cross_resp = client.get(
        f"/admin/clinics/{second['clinic_id']}/config",
        headers={"Authorization": f"Bearer {first['access_token']}"},
    )
    assert cross_resp.status_code == 403
