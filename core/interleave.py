def parse_ratio(ratio_str: str) -> dict:
    """Parse a "standard:priority" ratio string, e.g. "2:1" -> {"standard": 2, "priority": 1}."""
    standard, priority = ratio_str.split(":")
    return {"standard": int(standard), "priority": int(priority)}


def next_subqueue(call_counter: int, ratio: dict) -> str:
    """Weighted round-robin over (standard, priority) using the session's call_counter."""
    cycle_length = ratio["standard"] + ratio["priority"]
    position_in_cycle = call_counter % cycle_length
    return "priority" if position_in_cycle < ratio["priority"] else "standard"


def predict_call_order(waiting_by_tier: dict, call_counter: int, ratio: dict) -> list:
    """Simulate the exact order call_next() would pull waiting items in, without mutating
    anything -- used to show staff the queue in its true call order rather than raw join
    order. `waiting_by_tier` = {"emergency": [...], "priority": [...], "standard": [...]},
    each already FIFO-sorted (earliest first). Items can be anything (token IDs, dicts,
    ORM objects) -- this function only ever reorders them, never inspects their contents.

    Mirrors core/queue_engine.py's call_next() precedence exactly: emergency items are
    always called first, in FIFO order, ahead of the interleave entirely; then priority
    and standard interleave per `ratio`, falling back to whichever tier still has people
    if the preferred one has run out (never stalling early)."""
    emergency = list(waiting_by_tier.get("emergency", []))
    priority = list(waiting_by_tier.get("priority", []))
    standard = list(waiting_by_tier.get("standard", []))

    order = list(emergency)
    counter = call_counter
    p_idx = s_idx = 0

    while p_idx < len(priority) or s_idx < len(standard):
        preferred = next_subqueue(counter, ratio)
        if preferred == "priority" and p_idx < len(priority):
            order.append(priority[p_idx])
            p_idx += 1
        elif preferred == "standard" and s_idx < len(standard):
            order.append(standard[s_idx])
            s_idx += 1
        elif s_idx < len(standard):  # preferred tier exhausted, fall back to the other
            order.append(standard[s_idx])
            s_idx += 1
        else:
            order.append(priority[p_idx])
            p_idx += 1
        counter += 1

    return order
