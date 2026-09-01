def backoff_seconds(attempt: int) -> int:
    """Exponential backoff: attempt 1 -> 2s, attempt 2 -> 4s, attempt 3 -> 8s."""
    return 2 ** attempt
