import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PatientContact(BaseModel):
    type: Literal["telegram", "email"]
    value: str

    def as_column_value(self) -> str:
        return f"{self.type}:{self.value}"


class JoinQueueRequest(BaseModel):
    patient_contact: PatientContact
    tier: Literal["standard", "priority"] = "standard"
    patient_email: str | None = None  # optional fallback contact if patient_contact's channel fails


class JoinQueueResponse(BaseModel):
    token_id: uuid.UUID
    display_number: str | None
    tier: str
    position: int
    estimated_wait_seconds: int
    fee_due_paise: int
    session_status: str


class TokenStatusResponse(BaseModel):
    token_id: uuid.UUID
    display_number: str | None
    tier: str
    status: str
    position: int | None
    estimated_wait_seconds: int | None
    session_status: str


class CallNextResponse(BaseModel):
    token_id: uuid.UUID
    display_number: str | None
    tier: str
    patient_contact: str
    called_at: datetime


class QueueTokenSummary(BaseModel):
    token_id: uuid.UUID
    display_number: str | None
    tier: str
    status: str
    patient_contact: str
    emergency_override: bool
    joined_at: datetime
    called_at: datetime | None
    paid: bool
    fee_amount_paise: int | None


class QueueListResponse(BaseModel):
    session_id: uuid.UUID
    session_status: str
    called: list[QueueTokenSummary]
    waiting: list[QueueTokenSummary]


class ServedTokenSummary(BaseModel):
    token_id: uuid.UUID
    display_number: str | None
    tier: str
    patient_contact: str
    served_at: datetime | None
    paid: bool
    fee_amount_paise: int


class ServedTodayResponse(BaseModel):
    session_id: uuid.UUID
    session_date: str
    served: list[ServedTokenSummary]
    total_collected_paise: int
    total_pending_paise: int


class NoShowResponse(BaseModel):
    token_id: uuid.UUID
    action: str
    new_called_token_id: uuid.UUID | None


class WalkInRequest(BaseModel):
    patient_contact: PatientContact
    tier: Literal["standard", "priority"] = "standard"
    patient_email: str | None = None


class EmergencyOverrideRequest(BaseModel):
    patient_contact: PatientContact


class MarkPaidRequest(BaseModel):
    fee_amount_paise: int = Field(ge=0)


class ChangeTierRequest(BaseModel):
    tier: Literal["standard", "priority"]


class UpdateContactRequest(BaseModel):
    patient_contact: PatientContact
    patient_email: str | None = None


class LoginRequest(BaseModel):
    contact: str
    password: str


class SignupRequest(BaseModel):
    clinic_name: str
    admin_name: str
    admin_contact: str
    admin_password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    clinic_id: uuid.UUID


class ClinicConfigResponse(BaseModel):
    clinic_id: uuid.UUID
    name: str
    priority_fee_paise: int
    standard_priority_ratio: str
    notify_lead_count: int
    timezone: str


class ClinicConfigUpdateRequest(BaseModel):
    name: str | None = None
    priority_fee_paise: int | None = None
    standard_priority_ratio: str | None = None
    notify_lead_count: int | None = None
    timezone: str | None = None


class StaffCreateRequest(BaseModel):
    name: str
    role: Literal["receptionist", "doctor", "admin"]
    contact: str
    password: str


class StaffResponse(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    contact: str


class DailyAnalyticsResponse(BaseModel):
    session_date: str
    served_count: int
    average_wait_seconds: float | None
    average_service_seconds: float | None
    no_show_count: int
    no_show_rate: float | None


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
