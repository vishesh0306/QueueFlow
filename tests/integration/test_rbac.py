import uuid

import bcrypt
import pytest

from api.deps import create_access_token
from db.models import Clinic, StaffAccount

ROLES = ("receptionist", "doctor", "admin")


@pytest.fixture
def clinic_and_tokens(db):
    clinic = Clinic(name="RBAC Test Clinic")
    db.add(clinic)
    db.flush()

    access_tokens = {}
    for role in ROLES:
        password_hash = bcrypt.hashpw(b"testpass123", bcrypt.gensalt()).decode()
        staff = StaffAccount(
            clinic_id=clinic.id, name=f"{role} user", role=role,
            contact=f"{role}@rbactest.local", password_hash=password_hash,
        )
        db.add(staff)
        db.flush()
        access_tokens[role] = create_access_token(staff.id, clinic.id, role)
    db.commit()
    return clinic, access_tokens


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _endpoints(clinic_id: uuid.UUID):
    dummy_token_id = uuid.uuid4()
    return [
        ("get", "/staff/queue", None, ROLES),
        ("post", "/staff/queue/call-next", {}, ROLES),
        ("post", f"/staff/queue/tokens/{dummy_token_id}/no-show", {}, ROLES),
        ("post", f"/staff/queue/tokens/{dummy_token_id}/mark-served", {}, ROLES),
        ("post", f"/staff/queue/tokens/{dummy_token_id}/mark-paid", {"fee_amount_paise": 0}, ROLES),
        ("post", f"/staff/queue/tokens/{dummy_token_id}/void-payment", {}, ROLES),
        ("post", f"/staff/queue/tokens/{dummy_token_id}/change-tier", {"tier": "priority"}, ROLES),
        ("post", "/staff/queue/walk-in",
         {"patient_contact": {"type": "email", "value": "a@b.com"}, "tier": "standard"}, ROLES),
        ("post", "/staff/queue/emergency-override",
         {"patient_contact": {"type": "email", "value": "a@b.com"}}, ("doctor", "admin")),
        ("post", "/staff/queue/pause", {}, ("doctor", "admin")),
        ("post", "/staff/queue/resume", {}, ("doctor", "admin")),
        ("post", "/staff/queue/close", {}, ("doctor", "admin")),
        ("get", f"/admin/clinics/{clinic_id}/config", None, ("admin",)),
        ("put", f"/admin/clinics/{clinic_id}/config", {"name": "New Name"}, ("admin",)),
        ("get", "/admin/analytics/daily", None, ("doctor", "admin")),
        ("get", "/admin/staff", None, ("admin",)),
        ("post", "/admin/staff",
         {"name": "New Staff", "role": "receptionist", "contact": "new@rbactest.local", "password": "x"},
         ("admin",)),
    ]


@pytest.mark.parametrize("role", ROLES)
def test_rbac_matrix(client, clinic_and_tokens, role):
    clinic, access_tokens = clinic_and_tokens
    header = _auth_header(access_tokens[role])

    for method, path, body, allowed_roles in _endpoints(clinic.id):
        call = getattr(client, method)
        response = call(path, headers=header) if body is None else call(path, headers=header, json=body)

        if role in allowed_roles:
            assert response.status_code not in (401, 403), (
                f"{role} should be permitted on {method.upper()} {path}, got {response.status_code}: {response.text}"
            )
        else:
            assert response.status_code == 403, (
                f"{role} should be forbidden on {method.upper()} {path}, got {response.status_code}: {response.text}"
            )


def test_missing_token_rejected(client):
    response = client.post("/staff/queue/call-next")
    assert response.status_code in (401, 403)  # HTTPBearer returns 403 with no Authorization header


def test_cross_clinic_admin_config_denied(client, db):
    own_clinic = Clinic(name="Own Clinic")
    other_clinic = Clinic(name="Other Clinic")
    db.add_all([own_clinic, other_clinic])
    db.flush()

    admin = StaffAccount(
        clinic_id=own_clinic.id, name="Admin", role="admin",
        contact="admin@own.local", password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
    )
    db.add(admin)
    db.flush()
    token = create_access_token(admin.id, own_clinic.id, "admin")
    db.commit()

    response = client.get(f"/admin/clinics/{other_clinic.id}/config", headers=_auth_header(token))
    assert response.status_code == 403
