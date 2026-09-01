from notifications.retry import backoff_seconds
from notifications.service import render_message


def test_backoff_is_exponential():
    assert [backoff_seconds(a) for a in (1, 2, 3)] == [2, 4, 8]


def test_render_message_prefers_display_number():
    job = {"clinic_name": "Sharma Clinic", "display_number": "S-5", "token_id": "abc-123"}
    assert render_message(job) == "Sharma Clinic: it's your turn now! (token S-5)"


def test_render_message_falls_back_to_token_id_when_no_display_number():
    job = {"clinic_name": "Sharma Clinic", "display_number": None, "token_id": "abc-123"}
    assert render_message(job) == "Sharma Clinic: it's your turn now! (token abc-123)"
