"""The queue of a walk-in session: the call order and the next arrival number."""

from types import SimpleNamespace

from ...queue import call_order, next_number


def entry(name, number=None, priority=False):
    return SimpleNamespace(name=name, arrival_number=number, is_priority=priority)


def names(entries):
    return [item.name for item in call_order(entries)]


def test_call_order(subtests):
    cases = {
        "by arrival number": ([entry("b", 2), entry("a", 1), entry("c", 3)], ["a", "b", "c"]),
        "priority first": ([entry("a", 1), entry("b", 2), entry("old", 3, True)], ["old", "a", "b"]),
        "among the priority ones, the number": (
            [entry("a", 1), entry("p2", 4, True), entry("p1", 2, True), entry("b", 3)],
            ["p1", "p2", "a", "b"],
        ),
        "who has not arrived comes after, in the order given": (
            [entry("late"), entry("a", 2), entry("later", priority=True), entry("p", 5, True)],
            ["p", "a", "late", "later"],
        ),
        "nobody": ([], []),
    }
    for name, (entries, expected) in cases.items():
        with subtests.test(name):
            assert names(entries) == expected


def test_call_order_takes_any_iterable_and_does_not_change_it():
    entries = [entry("b", 2), entry("a", 1)]
    assert names(item for item in entries) == ["a", "b"]
    assert [item.name for item in entries] == ["b", "a"]


def test_next_number(subtests):
    cases = {
        "the first": ([], 1),
        "nobody arrived yet": ([None, None], 1),
        "after the highest": ([1, 2, None], 3),
        "a gap is not filled": ([1, 5], 6),
    }
    for name, (numbers, expected) in cases.items():
        with subtests.test(name):
            assert next_number(numbers) == expected
