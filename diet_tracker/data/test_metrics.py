# tests/test_metrics.py
"""
Tests for daily metrics:
- Per-day stats within a single day window (entries in/out of the day).
- Edge-inclusion (start-of-day inclusive, end-of-day inclusive by given inputs).
- Period aggregation across multiple days, including empty, food-only, and mixed cases.
"""

from datetime import datetime, timedelta

import pytest

from diet_tracker.data.metrics import get_daily_stats, get_daily_stats_period, round_sod
from diet_tracker.data.table_helpers import (
    close_current_cycle,
    create_cycle,
    create_exercise_entry,
    create_food_entry,
)
from diet_tracker.data.tables import Cycle, ExerciseEntry, FoodEntry, init_database
from diet_tracker.data.test_tables import _dt

# -----------------------
# Fixtures & helpers
# -----------------------


@pytest.fixture(scope="function")
def user_id():
    """Use a stable user id across tests."""
    return "1"


@pytest.fixture(scope="function")
def sessionmaker(tmp_path, user_id):
    """
    Provide a Session factory bound to a fresh on-disk SQLite DB per test.
    Mirrors direct calls to init_database(user_id, tmp_path).
    """
    _, sessionmaker = init_database(user_id, tmp_path)
    return sessionmaker


def _open_cycle(
    session, maintenance_kcal=1800, start_dt=None
) -> Cycle:  # pragma: no cover
    """
    Create a Cycle with the provided maintenance_kcal and start_dt (default=_dt(0)),
    then persist via create_cycle. Returns the managed Cycle.
    """
    if start_dt is None:
        start_dt = _dt(0)
    c = Cycle(
        start_dt=start_dt, maintenance_kcal=maintenance_kcal, daily_deficit_goal=600
    )
    create_cycle(session, c)
    return c


# -----------------------
# Daily stats (single day)
# -----------------------


def test_get_daily_stats_result(tmp_path, user_id, sessionmaker):
    """
    get_daily_stats should include entries that fall on the reference day and
    compute kcal_in/out/maintenance/deficit as expected.
    """
    with sessionmaker.begin() as session:
        c = _open_cycle(session, maintenance_kcal=1800, start_dt=_dt(0))
        # Maintain original ordering and timestamps
        food_entries = [
            FoodEntry(name="Food", kcal=200, dt=_dt(100)),
            FoodEntry(name="Food", kcal=400, dt=_dt(400)),
            FoodEntry(name="Food", kcal=400, dt=_dt(300)),
        ]
        c.food_entries.extend(food_entries)

        exercise_entries = [
            ExerciseEntry(name="Exercise", kcal=200, dt=_dt(100)),
            ExerciseEntry(name="Exercise", kcal=300, dt=_dt(100)),
            ExerciseEntry(name="Exercise", kcal=400, dt=_dt(300)),
        ]
        c.exercise_entries.extend(exercise_entries)

    stats = get_daily_stats(user_id, tmp_path, _dt(50))
    assert len(food_entries) == len(stats.food_entries)
    assert len(exercise_entries) == len(stats.exercise_entries)
    assert stats.kcal_in == 1000
    assert stats.kcal_out == 900
    assert stats.maintenance == 1800
    assert stats.deficit == 1700
    assert stats.dt == _dt(0).date()


def test_daily_stats_no_entries_or_outside_day_range(tmp_path, user_id, sessionmaker):
    """
    Entries outside the day window should be excluded; empty day yields zero totals.
    """
    with sessionmaker.begin() as session:
        c = _open_cycle(session, maintenance_kcal=1800, start_dt=_dt(0))
        # Outside the day window on both sides
        c.food_entries.append(FoodEntry(name="Food1", kcal=200, dt=_dt(-90_000)))
        c.food_entries.append(FoodEntry(name="Food2", kcal=200, dt=_dt(90_000)))
        c.exercise_entries.append(
            ExerciseEntry(name="Exercise1", kcal=200, dt=_dt(-90_000))
        )
        c.exercise_entries.append(
            ExerciseEntry(name="Exercise2", kcal=200, dt=_dt(90_000))
        )

    stats = get_daily_stats(user_id, tmp_path, _dt(50))
    assert 0 == len(stats.food_entries)
    assert 0 == len(stats.exercise_entries)
    assert stats.kcal_in == 0
    assert stats.kcal_out == 0
    assert stats.maintenance == 0
    assert stats.deficit == 0
    assert stats.deficit_goal == 0
    assert stats.dt == _dt(0).date()


def test_daily_stats_no_cycle_or_closed_cycle(tmp_path, user_id, sessionmaker):
    """
    If no open cycle stats should return None
    """
    stats = get_daily_stats(user_id, tmp_path, _dt(50))
    assert stats is None
    with sessionmaker.begin() as session:
        _open_cycle(session, maintenance_kcal=1800, start_dt=_dt(0))
        close_current_cycle(session)

    stats = get_daily_stats(user_id, tmp_path, _dt(50))
    assert stats is None


def test_daily_stats_entries_on_edge(tmp_path, user_id, sessionmaker):
    """
    Entries exactly at the lower or upper day edges should be included;
    just outside the edges should be excluded.
    """
    lower_edge = _dt(0).replace(hour=0, minute=0, second=0, microsecond=0)
    less_lower_edge = lower_edge + timedelta(seconds=-1)
    upper_edge = _dt(0).replace(hour=23, minute=59, second=59, microsecond=0)
    more_upper_edge = upper_edge + timedelta(seconds=1)

    with sessionmaker.begin() as session:
        c = _open_cycle(session, maintenance_kcal=1800, start_dt=_dt(0))

        # Included at lower edge; excluded just before
        session.add_all(
            [
                FoodEntry(name="Food1", kcal=200, dt=lower_edge, cycle_id=c.id),
                FoodEntry(name="Food2", kcal=300, dt=less_lower_edge, cycle_id=c.id),
                ExerciseEntry(name="Exercise1", kcal=200, dt=lower_edge, cycle_id=c.id),
                ExerciseEntry(
                    name="Exercise2", kcal=300, dt=less_lower_edge, cycle_id=c.id
                ),
            ]
        )

        # Included at upper edge; excluded just after
        session.add_all(
            [
                FoodEntry(name="Food3", kcal=400, dt=upper_edge, cycle_id=c.id),
                FoodEntry(name="Food4", kcal=500, dt=more_upper_edge, cycle_id=c.id),
                ExerciseEntry(name="Exercise3", kcal=200, dt=upper_edge, cycle_id=c.id),
                ExerciseEntry(
                    name="Exercise4", kcal=300, dt=more_upper_edge, cycle_id=c.id
                ),
            ]
        )

    stats = get_daily_stats(user_id, tmp_path, _dt(50))
    assert 2 == len(stats.food_entries)
    assert 2 == len(stats.exercise_entries)
    assert stats.kcal_in == 600
    assert stats.kcal_out == 400
    assert stats.maintenance == 1800
    assert stats.deficit == 1600
    assert stats.dt == _dt(0).date()


# -----------------------
# Period stats
# -----------------------


def test_daily_stats_period_result_and_outside_period(tmp_path, user_id, sessionmaker):
    """
    get_daily_stats_period should aggregate over [period_start, period_end] by day,
    including exactly 7 days in-range and excluding entries outside that window.
    """
    ref_date = round_sod(datetime.now())
    period_start = ref_date - timedelta(days=2)
    period_end = ref_date + timedelta(days=4)

    with sessionmaker.begin() as session:
        _open_cycle(
            session, maintenance_kcal=1800, start_dt=ref_date - timedelta(days=100)
        )

        # 7 in-range days
        for i in range(7):
            create_food_entry(
                session,
                FoodEntry(
                    name="Food", kcal=100, dt=period_start + (timedelta(days=1) * i)
                ),
            )
            create_exercise_entry(
                session,
                ExerciseEntry(
                    name="Exercise", kcal=50, dt=period_start + (timedelta(days=1) * i)
                ),
            )

        # After the window → ignored
        for i in range(7, 10):
            create_food_entry(
                session,
                FoodEntry(
                    name="Food", kcal=100, dt=period_start + (timedelta(days=1) * i)
                ),
            )
            create_exercise_entry(
                session,
                ExerciseEntry(
                    name="Exercise", kcal=50, dt=period_start + (timedelta(days=1) * i)
                ),
            )

        # Before the window → ignored
        for i in range(-1, -5, -1):
            create_food_entry(
                session,
                FoodEntry(
                    name="Food", kcal=100, dt=period_start + (timedelta(days=1) * i)
                ),
            )
            create_exercise_entry(
                session,
                ExerciseEntry(
                    name="Exercise", kcal=50, dt=period_start + (timedelta(days=1) * i)
                ),
            )

    period_stats = get_daily_stats_period(user_id, tmp_path, period_start, period_end)

    assert period_stats.kcal_in == 700
    assert period_stats.kcal_out == 350
    assert period_stats.maintenance == 1800 * 7
    # We do not consider current day
    assert period_stats.deficit == (1800 - 50) * 6
    assert period_stats.deficit_goal == 600 * 7
    assert period_stats.daily_stats[-1].dt == period_end.date()


def test_daily_stats_period_empty(tmp_path, user_id, sessionmaker):
    """
    With no entries in the period, totals should be zeros for in/out
    and maintenance should be days_in_period * maintenance_kcal.
    """
    ref_date = round_sod(datetime.now())
    period_start = ref_date - timedelta(days=2)
    period_end = ref_date + timedelta(days=4)

    with sessionmaker.begin() as session:
        _open_cycle(
            session, maintenance_kcal=1800, start_dt=ref_date - timedelta(days=100)
        )

    period_stats = get_daily_stats_period(user_id, tmp_path, period_start, period_end)

    assert period_stats.kcal_in == 0
    assert period_stats.kcal_out == 0
    assert period_stats.maintenance == 0
    assert period_stats.deficit == 0
    assert period_stats.deficit_goal == 0


def test_daily_stats_period_food_only(tmp_path, user_id, sessionmaker):
    """
    When only food entries are present, kcal_out should be zero and deficit reflects
    maintenance - kcal_in per day.
    """
    ref_date = round_sod(datetime.now())
    period_start = ref_date - timedelta(days=2)
    period_end = ref_date + timedelta(days=4)

    with sessionmaker.begin() as session:
        _open_cycle(
            session, maintenance_kcal=1800, start_dt=ref_date - timedelta(days=100)
        )
        for i in range(7):
            create_food_entry(
                session,
                FoodEntry(
                    name="Food", kcal=100, dt=period_start + (timedelta(days=1) * i)
                ),
            )

    period_stats = get_daily_stats_period(user_id, tmp_path, period_start, period_end)

    assert period_stats.kcal_in == 700
    assert period_stats.kcal_out == 0
    assert period_stats.maintenance == 1800 * 7
    # We do not consider current day
    assert period_stats.deficit == 1700 * 6
    assert period_stats.deficit_goal == 600 * 7
