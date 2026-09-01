def parse_ratio(ratio_str: str) -> dict:
    """Parse a "standard:priority" ratio string, e.g. "2:1" -> {"standard": 2, "priority": 1}."""
    standard, priority = ratio_str.split(":")
    return {"standard": int(standard), "priority": int(priority)}


def next_subqueue(call_counter: int, ratio: dict) -> str:
    """Weighted round-robin over (standard, priority) using the session's call_counter."""
    cycle_length = ratio["standard"] + ratio["priority"]
    position_in_cycle = call_counter % cycle_length
    return "priority" if position_in_cycle < ratio["priority"] else "standard"
