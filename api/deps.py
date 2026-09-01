import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12

_bearer_scheme = HTTPBearer()


class APIError(Exception):
    """Raised by route handlers to produce the standard {"error": {"code", "message"}} envelope (LLD §10)."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class JWTClaims(BaseModel):
    staff_id: uuid.UUID
    clinic_id: uuid.UUID
    role: str


def create_access_token(staff_id: uuid.UUID, clinic_id: uuid.UUID, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(staff_id),
        "clinic_id": str(clinic_id),
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def get_current_claims(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> JWTClaims:
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(401, detail="Invalid or expired token")
    return JWTClaims(staff_id=payload["sub"], clinic_id=payload["clinic_id"], role=payload["role"])


def require_role(*allowed: str):
    """RBAC dependency factory: checks the JWT role, and — when the route has a
    {clinic_id} path param — that it matches the caller's own clinic (LLD §9)."""

    def dependency(request: Request, claims: JWTClaims = Depends(get_current_claims)) -> JWTClaims:
        if claims.role not in allowed:
            raise HTTPException(403, detail="Not permitted for this role")
        path_clinic_id = request.path_params.get("clinic_id")
        if path_clinic_id is not None and str(claims.clinic_id) != path_clinic_id:
            raise HTTPException(403, detail="Cross-clinic access denied")
        return claims

    return dependency
