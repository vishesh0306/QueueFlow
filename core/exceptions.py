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


class PatientAlreadyCalledError(Exception):
    """v1 assumes a single doctor, so at most one token can be 'called' at a time. Raised
    when call_next() is invoked while a previous call is still unresolved (not yet marked
    served/no-show/cancelled) -- including when a no-show swap silently promoted a new
    token to 'called' as a side effect that nobody has acted on yet."""

    def __init__(self, session_id: uuid.UUID, called_token_id: uuid.UUID):
        super().__init__(f"Session {session_id} already has an unresolved called token {called_token_id}")
        self.session_id = session_id
        self.called_token_id = called_token_id


class DuplicateBookingError(Exception):
    """Raised when a contact tries to join a session it already has an active (waiting
    or called) token in. There's no real patient identity in v1 -- patient_contact is
    the closest proxy to "the same person" -- so this is a same-string match, not a
    guaranteed same-person one."""

    def __init__(self, session_id: uuid.UUID, patient_contact: str):
        super().__init__(f"{patient_contact} already has an active token in session {session_id}")
        self.session_id = session_id
        self.patient_contact = patient_contact
