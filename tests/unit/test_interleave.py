from core.interleave import next_subqueue, parse_ratio, predict_call_order


def test_parse_ratio():
    assert parse_ratio("2:1") == {"standard": 2, "priority": 1}


def test_two_to_one_ratio_produces_expected_sequence():
    ratio = {"standard": 2, "priority": 1}
    result = [next_subqueue(c, ratio) for c in range(6)]
    assert result == ["priority", "standard", "standard",
                       "priority", "standard", "standard"]


def test_one_to_one_ratio_alternates():
    ratio = {"standard": 1, "priority": 1}
    result = [next_subqueue(c, ratio) for c in range(4)]
    assert result == ["priority", "standard", "priority", "standard"]


def test_ratio_holds_proportion_over_full_cycles():
    ratio = {"standard": 3, "priority": 1}
    result = [next_subqueue(c, ratio) for c in range(8)]
    assert result.count("priority") == 2
    assert result.count("standard") == 6


# ---- predict_call_order ---------------------------------------------------

def test_predict_call_order_matches_the_2_to_1_pattern():
    ratio = {"standard": 2, "priority": 1}
    waiting = {"priority": ["P1", "P2"], "standard": ["S1", "S2", "S3", "S4"]}

    order = predict_call_order(waiting, call_counter=0, ratio=ratio)

    assert order == ["P1", "S1", "S2", "P2", "S3", "S4"]


def test_predict_call_order_places_a_new_priority_arrival_correctly():
    """The exact scenario from the user: S1-S4 already waiting, then P1 arrives.
    Where P1 lands depends on the session's current call_counter, not on join order."""
    ratio = {"standard": 2, "priority": 1}
    waiting = {"priority": ["P1"], "standard": ["S1", "S2", "S3", "S4"]}

    # counter=0 -> priority is due immediately, P1 goes first despite joining last
    assert predict_call_order(waiting, call_counter=0, ratio=ratio) == ["P1", "S1", "S2", "S3", "S4"]

    # counter=1 -> standard is due first; priority isn't due again until position 0 of
    # the next cycle, i.e. after 2 more standard calls
    assert predict_call_order(waiting, call_counter=1, ratio=ratio) == ["S1", "S2", "P1", "S3", "S4"]


def test_predict_call_order_falls_back_when_a_tier_runs_out():
    ratio = {"standard": 2, "priority": 1}
    waiting = {"priority": ["P1", "P2", "P3"], "standard": ["S1"]}

    order = predict_call_order(waiting, call_counter=0, ratio=ratio)

    # S1 gets consumed on its one turn; every remaining slot correctly falls back to priority
    assert order == ["P1", "S1", "P2", "P3"]


def test_predict_call_order_puts_emergency_first_ahead_of_everything():
    ratio = {"standard": 2, "priority": 1}
    waiting = {"emergency": ["E1", "E2"], "priority": ["P1"], "standard": ["S1", "S2"]}

    order = predict_call_order(waiting, call_counter=0, ratio=ratio)

    assert order == ["E1", "E2", "P1", "S1", "S2"]


def test_predict_call_order_reflects_a_no_show_swap_reinsertion_point():
    """A no-show swap reinserts the no-show patient right behind the partner -- this
    function doesn't know anything about swaps, it just orders whatever's handed to it,
    so feeding it the post-swap standard queue should place the swapped token correctly."""
    ratio = {"standard": 2, "priority": 1}
    # After A no-shows and swaps with B, A is reinserted immediately behind B's old
    # slot -- ahead of C, who joined later and was never touched.
    waiting = {"priority": [], "standard": ["A", "C"]}  # B is the one currently called, not waiting

    order = predict_call_order(waiting, call_counter=1, ratio=ratio)

    assert order == ["A", "C"]
