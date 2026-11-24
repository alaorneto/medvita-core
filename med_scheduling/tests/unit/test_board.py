"""The board of the day (#135): the rows of the axis, where an item sits and the lanes of the items that cross."""

from ...board import MAX_LANES, MAX_ROWS, Axis, axis_of, lanes


def hours(text):
    first, last = text.split("-")
    return tuple(int(part[:2]) * 60 + int(part[3:]) for part in (first, last))


def test_the_axis_runs_from_the_hour_of_the_first_start_to_the_hour_after_the_last_end():
    axis = axis_of([hours("08:30-12:00"), hours("14:00-17:40")])
    assert (axis.first, axis.last) == (8 * 60, 18 * 60)
    assert axis_of([]) is None and axis_of([(600, 600)]) is None


def test_the_step_is_the_longest_every_bound_falls_on():
    assert axis_of([hours("08:00-12:00"), hours("08:45-09:15")]).step == 15
    assert axis_of([hours("08:00-12:00"), hours("08:20-08:40")]).step == 10
    assert axis_of([hours("08:00-12:00"), hours("08:05-08:25")]).step == 5
    # Off every step: 15 minutes, and the items round.
    assert axis_of([hours("08:00-09:00"), hours("08:07-08:31")]).step == 15


def test_a_long_day_keeps_to_the_rows_the_stylesheet_has():
    # Fifteen hours at 5 minutes would be 180 rows: the axis takes a longer step.
    axis = axis_of([hours("06:00-21:00"), hours("08:05-08:10")])
    assert axis.rows <= MAX_ROWS and axis.step == 15
    whole = axis_of([(0, 1440)])
    assert (whole.first, whole.last, whole.rows) == (0, 1440, MAX_ROWS)


def test_an_item_takes_the_rows_of_its_start_and_its_length():
    axis = Axis(8 * 60, 12 * 60, 15)
    assert axis.rows == 16
    assert axis.place(*hours("08:00-08:30")) == (1, 2)
    assert axis.place(*hours("09:15-10:00")) == (6, 3)
    assert axis.place(*hours("11:45-12:00")) == (16, 1)
    # A start off the step rounds down and an end rounds up; a short item takes one row.
    assert axis.place(*hours("08:10-08:20")) == (1, 2)
    assert axis.place(*hours("08:00-08:05")) == (1, 1)
    # What passes the axis is clipped to it; what is outside has no place.
    assert axis.place(*hours("07:00-08:30")) == (1, 2)
    assert axis.place(*hours("11:30-13:00")) == (15, 2)
    assert axis.place(*hours("12:00-13:00")) is None and axis.place(*hours("06:00-08:00")) is None


def test_the_labels_of_the_axis_are_the_whole_hours():
    assert Axis(8 * 60, 11 * 60, 15).hours() == [("08:00", 1, 4), ("09:00", 5, 4), ("10:00", 9, 4)]
    assert Axis(23 * 60, 24 * 60, 10).hours() == [("23:00", 1, 6)]


def test_items_that_cross_take_lanes_side_by_side():
    assert lanes([]) == ([], 1)
    assert lanes([(1, 2), (3, 2), (5, 1)]) == ([1, 1, 1], 1)
    # A fit-in over an appointment, and the next item back on the first lane.
    assert lanes([(1, 2), (2, 1), (3, 2)]) == ([1, 2, 1], 2)
    # The lanes follow the rows, whatever the order of the list.
    assert lanes([(3, 2), (1, 4)]) == ([2, 1], 2)


def test_past_the_last_lane_items_share_it():
    found, count = lanes([(1, 4)] * (MAX_LANES + 2))
    assert count == MAX_LANES and found == [1, 2, 3, 3, 3]
