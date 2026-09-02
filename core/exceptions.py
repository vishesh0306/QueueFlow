import uuid


class QueueEmptyError(Exception):
    def __init__(self, session_id: uuid.UUID):
        super().__init__(f"No waiting tokens in session {session_id}")
        self.session_id = session_id


class InvalidTransitionError(Exception):
    pass


class SessionClosedError(Exception):
    def __init__(self, clinic_id: uuid.UUID):
        super().__init__(f"Clinic {clinic_id}'s queue is not currently accepting new tokens")
        self.clinic_id = clinic_id


class NoDoctorConfiguredError(Exception):
    def __init__(self, clinic_id: uuid.UUID):
        super().__init__(f"Clinic {clinic_id} has no doctor account configured")
        self.clinic_id = clinic_id


class SessionNotActiveError(Exception):
    """Raised when call_next() is attempted on a paused/closed session (emergency-override
    tokens bypass this — a genuine urgent case shouldn't have to wait on a lunch-break pause)."""

    def __init__(self, session_id: uuid.UUID, status: str):
        super().__init__(f"Session {session_id} is '{status}', not accepting call-next right now")
        self.session_id = session_id
        self.status = status
