from dataclasses import dataclass


@dataclass
class SendResult:
    ok: bool
    error: str | None = None
