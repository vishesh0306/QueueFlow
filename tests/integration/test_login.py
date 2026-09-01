import bcrypt

from db.models import Clinic, StaffAccount


def _make_staff(db, password="correct-password"):
    clinic = Clinic(name="Login Test Clinic")
    db.add(clinic)
    db.flush()
    staff = StaffAccount(
        clinic_id=clinic.id, name="Receptionist", role="receptionist", contact="recep@login.local",
        password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
    )
    db.add(staff)
    db.commit()
    return clinic, staff


def test_login_with_correct_credentials_returns_token(client, db):
    clinic, staff = _make_staff(db)

    response = client.post("/staff/login", json={"contact": "recep@login.local", "password": "correct-password"})

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "receptionist"
    assert body["clinic_id"] == str(clinic.id)
    assert body["access_token"]


def test_login_with_wrong_password_rejected(client, db):
    _make_staff(db)

    response = client.post("/staff/login", json={"contact": "recep@login.local", "password": "wrong"})

    assert response.status_code == 401


def test_login_with_unknown_contact_rejected(client, db):
    response = client.post("/staff/login", json={"contact": "nobody@login.local", "password": "x"})

    assert response.status_code == 401
