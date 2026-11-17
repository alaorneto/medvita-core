def test_ci_must_fail():
    assert 1 == 2  # Discarded commit: proves the CI refuses a failing test (A3).
