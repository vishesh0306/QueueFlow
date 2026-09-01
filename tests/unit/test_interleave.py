from core.interleave import next_subqueue, parse_ratio


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
