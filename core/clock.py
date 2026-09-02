from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today_in(tz_name: str, *, now: datetime | None = None) -> date:
    """The calendar date in a clinic's own timezone, not the server's. A clinic in
    Asia/Kolkata (UTC+5:30) has already rolled over to tomorrow while a UTC server
    clock still reads yesterday evening -- using date.today() there would open a new
    "today" session hours early, or keep serving into the wrong day's session."""
    moment = now if now is not None else utcnow()
    return moment.astimezone(ZoneInfo(tz_name)).date()
