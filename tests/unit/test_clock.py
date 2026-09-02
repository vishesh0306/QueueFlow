from datetime import datetime, timezone

from core.clock import today_in


def test_today_in_rolls_over_ahead_of_utc_for_a_positive_offset_timezone():
    """23:30 UTC on the 1st is already 05:00 on the 2nd in Asia/Kolkata (UTC+5:30)."""
    moment = datetime(2026, 9, 1, 23, 30, tzinfo=timezone.utc)

    assert today_in("Asia/Kolkata", now=moment).isoformat() == "2026-09-02"


def test_today_in_stays_behind_utc_for_a_negative_offset_timezone():
    """01:00 UTC on the 2nd is still 20:00 on the 1st in America/New_York (UTC-5)."""
    moment = datetime(2026, 9, 2, 1, 0, tzinfo=timezone.utc)

    assert today_in("America/New_York", now=moment).isoformat() == "2026-09-01"


def test_today_in_matches_utc_date_for_utc_itself():
    moment = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)

    assert today_in("UTC", now=moment).isoformat() == "2026-09-02"
