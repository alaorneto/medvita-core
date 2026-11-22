"""The forms of the weekly grid: periods typed for several weekdays, and where each mistake is told."""

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from ...forms import DayForm, DayPeriod, Period, PeriodForm, PeriodsForm, clock

FROM = "2026-01-01"


def kind(name="Unimed"):
    return SimpleNamespace(sysid=uuid4(), name=name)


def existing(weekday, start, end, valid_from=date(2026, 1, 1), valid_until=None):
    """A period the grid already has, as the service gives it."""
    return SimpleNamespace(
        weekday=weekday, start_minute=start, end_minute=end, valid_from=valid_from, valid_until=valid_until
    )


def periods_form(data, **options):
    return PeriodsForm({"valid_from": FROM, **data}, **options)


def shapes(periods):
    return [(item.weekday, item.start_minute, item.end_minute) for item in periods]


def test_each_hour_line_becomes_a_period_on_every_ticked_weekday():
    insured, private = kind(), kind("Particular")
    form = periods_form(
        {
            "weekdays": ["2", "0"],
            "start_1": "08:00",
            "end_1": "12:00",
            "start_3": "14:00",
            "end_3": "18:00",
            "kinds": [str(insured.sysid)],
            "valid_until": "2026-12-31",
        },
        kinds=(insured, private),
    )
    assert form.is_valid(), form.errors
    assert shapes(form.periods) == [(0, 480, 720), (0, 840, 1080), (2, 480, 720), (2, 840, 1080)]
    assert {item.kinds for item in form.periods} == {(insured.sysid,)}
    assert {(item.valid_from, item.valid_until) for item in form.periods} == {(date(2026, 1, 1), date(2026, 12, 31))}
    assert [item.field for item in form.periods] == ["start_1", "start_3", "start_1", "start_3"]


def test_three_periods_on_the_same_day_and_no_kind_ticked():
    form = periods_form(
        {
            "weekdays": ["4"],
            "start_1": "07:00",
            "end_1": "09:00",
            "start_2": "10:00",
            "end_2": "12:00",
            "start_3": "13:00",
            "end_3": "00:00",
        },
        kinds=(kind(),),
    )
    assert form.is_valid(), form.errors
    assert shapes(form.periods) == [(4, 420, 540), (4, 600, 720), (4, 780, 1440)]
    assert all(item.kinds == () and item.valid_until is None for item in form.periods)


def test_mistakes_are_told_on_the_field(subtests):
    line = {"weekdays": ["0"], "start_1": "08:00", "end_1": "12:00"}
    cases = {
        "no weekday": ({**line, "weekdays": []}, "weekdays", "Marque ao menos um dia"),
        "the first hours are required": ({"weekdays": ["0"], "end_1": "12:00"}, "start_1", ""),
        "an end without a start": ({**line, "end_2": "15:00"}, "start_2", "Informe o início e o fim"),
        "a start without an end": ({**line, "start_3": "15:00"}, "end_3", "Informe o início e o fim"),
        "the end before the start": ({**line, "start_2": "15:00", "end_2": "14:00"}, "end_2", "depois do início"),
        "the end equal to the start": ({**line, "end_1": "08:00"}, "end_1", "depois do início"),
        "the validity upside down": ({**line, "valid_until": "2025-12-31"}, "valid_until", "termina antes"),
        "a kind the schedule does not take": ({**line, "kinds": [str(uuid4())]}, "kinds", ""),
        "two lines typed over each other": (
            {**line, "start_2": "11:00", "end_2": "13:00"},
            "start_2",
            "Segunda: 11:00–13:00 se sobrepõe ao período 08:00–12:00",
        ),
    }
    for name, (data, field, text) in cases.items():
        with subtests.test(name):
            form = periods_form(data, kinds=(kind(),))
            assert not form.is_valid() and set(form.errors) == {field}, form.errors
            assert text in " ".join(form.errors[field]) and form.periods == []


def test_an_overlap_with_the_grid_names_the_weekday_and_the_period(subtests):
    grid = (existing(0, 480, 720), existing(2, 840, 1080, valid_until=date(2025, 12, 31)))
    data = {"weekdays": ["0", "1", "2"], "start_1": "07:00", "end_1": "09:00", "start_2": "14:00", "end_2": "16:00"}
    with subtests.test("only the line and the weekday that cross"):
        form = periods_form(data, existing=grid)
        assert not form.is_valid() and set(form.errors) == {"start_1"}
        (error,) = form.errors["start_1"]
        assert "Segunda: 07:00–09:00 se sobrepõe ao período 08:00–12:00" in error
    with subtests.test("a period that ended does not cross one that starts later"):
        form = periods_form({**data, "weekdays": ["2"]}, existing=grid)
        assert form.is_valid(), form.errors
        assert shapes(form.periods) == [(2, 420, 540), (2, 840, 960)]
    with subtests.test("touching ends are two periods"):
        form = periods_form({"weekdays": ["0"], "start_1": "12:00", "end_1": "13:00"}, existing=grid)
        assert form.is_valid(), form.errors


def test_the_empty_lines_are_marked_for_the_page():
    blank = PeriodsForm(initial={"valid_from": date(2026, 1, 1)})
    assert [(line["number"], line["empty"]) for line in blank.lines()] == [(1, True), (2, True), (3, True)]
    typed = periods_form({"weekdays": ["0"], "start_1": "08:00", "end_1": "09:00", "end_3": "11:00"})
    assert [line["empty"] for line in typed.lines()] == [False, True, False]
    # The hours first, then how the period sees its patients, then the kinds it takes.
    hours = ["start_1", "end_1", "start_2", "end_2", "start_3", "end_3"]
    assert list(typed.fields)[:10] == ["weekdays", *hours, "mode", "capacity", "kinds"]


def test_one_period_is_changed_against_the_others(subtests):
    insured = kind()
    others = (existing(0, 840, 1080),)
    data = {"weekday": "0", "start": "08:00", "end": "12:00", "valid_from": FROM}
    with subtests.test("read"):
        form = PeriodForm({**data, "kinds": [str(insured.sysid)]}, kinds=(insured,), existing=others)
        assert form.is_valid(), form.errors
        assert form.period == Period(0, 480, 720, date(2026, 1, 1), None, (insured.sysid,), "start")
    with subtests.test("over another period of the day"):
        form = PeriodForm({**data, "end": "15:00"}, kinds=(insured,), existing=others)
        assert not form.is_valid() and set(form.errors) == {"start"} and form.period is None
        assert "se sobrepõe ao período 14:00–18:00" in form.errors["start"][0]
    with subtests.test("moved to a free weekday"):
        form = PeriodForm({**data, "weekday": "3", "end": "15:00"}, existing=others)
        assert form.is_valid() and shapes([form.period]) == [(3, 480, 900)]
    with subtests.test("an unknown weekday"):
        form = PeriodForm({**data, "weekday": "7"}, existing=others)
        assert not form.is_valid() and set(form.errors) == {"weekday"}


def test_the_clock_of_the_page():
    assert [clock(minutes) for minutes in (0, 485, 720, 1439, 1440)] == ["00:00", "08:05", "12:00", "23:59", "24:00"]


def test_the_periods_of_one_day_are_read_line_by_line(subtests):
    insured, private = kind(), kind("Particular")
    kinds = (insured, private)
    with subtests.test("each line with hours is a period, in the order of the day"):
        form = DayForm(
            {
                "start_1": "14:00",
                "end_1": "00:00",
                "start_3": "08:00",
                "end_3": "12:00",
                "mode_3": "walk_in",
                "capacity_3": "15",
                "kinds_3": [str(insured.sysid)],
            },
            kinds=kinds,
        )
        assert form.is_valid(), form.errors
        assert form.periods == [
            DayPeriod(480, 720, "walk_in", 15, (insured.sysid,)),
            DayPeriod(840, 1440, "booked", None, ()),
        ]
    with subtests.test("the lines of the page"):
        blank = DayForm(initial={"start_1": "08:00", "end_1": "12:00"}, lines=5)
        assert [(line["number"], line["empty"]) for line in blank.lines()] == [
            (1, False),
            (2, True),
            (3, True),
            (4, True),
            (5, True),
        ]
        assert list(blank.fields)[:5] == ["start_1", "end_1", "mode_1", "capacity_1", "kinds_1"]
        assert "data-period-mode" in str(blank["mode_2"])
    cases = {
        "no period at all": ({}, "start_1", "Informe ao menos um período"),
        "half a period": ({"start_1": "08:00"}, "end_1", "Informe o início e o fim"),
        "an end before the start": ({"start_1": "12:00", "end_1": "08:00"}, "end_1", "depois do início"),
        "two periods over each other": (
            {"start_1": "08:00", "end_1": "12:00", "start_2": "11:00", "end_2": "13:00"},
            "start_2",
            "11:00–13:00 se sobrepõe ao período 08:00–12:00",
        ),
        "places in booked time": (
            {"start_1": "08:00", "end_1": "12:00", "capacity_1": "5"},
            "capacity_1",
            "Vagas valem só na ordem de chegada",
        ),
        "a line with places and no hours": (
            {"start_1": "08:00", "end_1": "12:00", "mode_2": "walk_in", "capacity_2": "5"},
            "start_2",
            "Informe o início e o fim",
        ),
        "no place at all": (
            {"start_1": "08:00", "end_1": "12:00", "mode_1": "walk_in", "capacity_1": "0"},
            "capacity_1",
            "",
        ),
        "an unknown mode": ({"start_1": "08:00", "end_1": "12:00", "mode_1": "queue"}, "mode_1", ""),
        "an unknown kind": ({"start_1": "08:00", "end_1": "12:00", "kinds_1": [str(uuid4())]}, "kinds_1", ""),
    }
    for name, (data, field, text) in cases.items():
        with subtests.test(name):
            form = DayForm(data, kinds=kinds)
            assert not form.is_valid() and set(form.errors) == {field}, form.errors
            assert text in form.errors[field][0] and form.periods == []
    with subtests.test("touching periods are two periods"):
        form = DayForm({"start_1": "08:00", "end_1": "12:00", "start_2": "12:00", "end_2": "13:00"})
        assert form.is_valid() and len(form.periods) == 2
    with subtests.test("a kind the schedule does not take in the mode of the line"):
        data = {"start_1": "08:00", "end_1": "12:00", "mode_1": "walk_in", "kinds_1": [str(private.sysid)]}
        form = DayForm(data, kinds=kinds, walk_in_kinds={insured.sysid})
        assert not form.is_valid() and "não atende por ordem de chegada: Particular" in form.errors["kinds_1"][0]
        assert DayForm({**data, "mode_1": "booked"}, kinds=kinds, walk_in_kinds={insured.sysid}).is_valid()
