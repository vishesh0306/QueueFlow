import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


StaffRole = ENUM("receptionist", "doctor", "admin", name="staff_role")
TokenTier = ENUM("standard", "priority", name="token_tier")
TokenStatus = ENUM(
    "waiting", "called", "served", "requeued", "cancelled", name="token_status"
)
SessionStatus = ENUM("active", "paused", "closed", name="session_status")
NotifChannel = ENUM("telegram", "email", name="notif_channel")
NotifStatus = ENUM("queued", "sent", "delivered", "failed", name="notif_status")


class Clinic(Base):
    __tablename__ = "clinics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    priority_fee_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    standard_priority_ratio: Mapped[str] = mapped_column(
        String(10), nullable=False, default="2:1"
    )
    notify_lead_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())

    staff_accounts: Mapped[list["StaffAccount"]] = relationship(back_populates="clinic")
    queue_sessions: Mapped[list["QueueSession"]] = relationship(back_populates="clinic")


class StaffAccount(Base):
    __tablename__ = "staff_accounts"
    __table_args__ = (UniqueConstraint("clinic_id", "contact"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(StaffRole, nullable=False)
    contact: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())

    clinic: Mapped["Clinic"] = relationship(back_populates="staff_accounts")


class QueueSession(Base):
    __tablename__ = "queue_sessions"
    __table_args__ = (UniqueConstraint("clinic_id", "doctor_id", "session_date"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_accounts.id"), nullable=False
    )
    session_date: Mapped[object] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(SessionStatus, nullable=False, default="active")
    call_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    standard_token_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority_token_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    emergency_token_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_show_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opened_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)

    clinic: Mapped["Clinic"] = relationship(back_populates="queue_sessions")
    tokens: Mapped[list["Token"]] = relationship(back_populates="session")


class Token(Base):
    __tablename__ = "tokens"
    __table_args__ = (
        Index("idx_tokens_session_status", "session_id", "status"),
        Index("idx_tokens_session_tier_seq", "session_id", "tier", "sequence_no"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("queue_sessions.id", ondelete="CASCADE"), nullable=False
    )
    patient_contact: Mapped[str] = mapped_column(String(120), nullable=False)
    patient_email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tier: Mapped[str] = mapped_column(TokenTier, nullable=False, default="standard")
    emergency_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(TokenStatus, nullable=False, default="waiting")
    sequence_no: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    swap_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_number: Mapped[str | None] = mapped_column(String(10), nullable=True)
    lead_notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    joined_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    called_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    served_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped["QueueSession"] = relationship(back_populates="tokens")
    payment: Mapped["Payment | None"] = relationship(back_populates="token", uselist=False)
    notification_logs: Mapped[list["NotificationLog"]] = relationship(back_populates="token")


class Payment(Base):
    __tablename__ = "payments"

    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.id", ondelete="CASCADE"), primary_key=True
    )
    fee_amount_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    collected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_accounts.id"), nullable=True
    )
    collected_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)

    token: Mapped["Token"] = relationship(back_populates="payment")


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(NotifChannel, nullable=False)
    status: Mapped[str] = mapped_column(NotifStatus, nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())

    token: Mapped["Token"] = relationship(back_populates="notification_logs")


class ServiceTimeSample(Base):
    __tablename__ = "service_time_samples"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("queue_sessions.id", ondelete="CASCADE"), nullable=False
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.id"), nullable=False
    )
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("duration_seconds > 0"),
        Index("idx_sts_session", "session_id", "recorded_at"),
    )
