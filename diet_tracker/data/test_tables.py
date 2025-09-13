# tests/test_tracker.py
"""
End-to-end tests for the diet tracker database layer.

These tests validate:
- Schema creation and basic CRUD for cycles, food, and exercise entries.
- Business rules (only one open cycle, close/open flow).
- Integrity constraints (non-negative kcal, maintenance kcal >= 1).
- Aggregations for current cycle and for arbitrary time periods.
- Correct cycle lookup semantics for arbitrary datetimes (inclusive start, exclusive end).
"""

import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from diet_tracker.data.table_helpers import (
    EntryNotFound,
    close_current_cycle,
    create_cycle,
    create_exercise_entry,
    create_food_entry,
    get_cycle_containing_datetime,
    get_total_exercise_calories_current_cycle,
    get_total_exercise_calories_for_period,
    get_total_food_calories_current_cycle,
    get_total_food_calories_for_period,
    read_all_cycles,
    read_current_cycle,
    remove_exercise_entry,
    remove_exercise_entry_by_id,
    remove_food_entry,
    remove_food_entry_by_id,
    update_exercise_entry,
    update_food_entry,
)
from diet_tracker.data.tables import (
    Cycle,
    ExerciseEntry,
    FoodEntry,
    init_database,
)

# -----------------------
# Fixtures & helpers
# -----------------------


@pytest.fixture(scope="function")
def db(tmp_path):
    """
    Create a fresh on-disk SQLite database (per test) using init_database(),
    which also enables foreign keys via PRAGMA.
    """
    user_id = "testuser"
    engine, SessionLocal = init_database(user_id=user_id, path=tmp_path)
    assert os.path.exists(tmp_path / f"{user_id}.sqlite")  # sanity check
    yield engine, SessionLocal
    engine.dispose()


@pytest.fixture(scope="function")
def session_factory(db):
    """Return a callable that creates a new SQLAlchemy session bound to the test DB."""
    _, SessionLocal = db

    def _make_session():
        return SessionLocal()

    return _make_session


def _dt(offset_seconds: int = 0) -> datetime:
    """UTC 'now' plus an offset in seconds (stable helper used across tests)."""
    return datetime.now() + timedelta(seconds=offset_seconds)


def _open_cycle(session, start_offset: int = 0) -> Cycle:
    """Create and return an open cycle starting at now + start_offset seconds."""
    c = Cycle(start_dt=_dt(start_offset))
    create_cycle(session, c)
    session.flush()
    session.refresh(c)
    return c


def _add_foods(session, cycle: Cycle, items):
    """
    Add multiple FoodEntry rows for a given cycle.

    items: iterable of tuples (name, kcal, dt_offset_seconds)
    """
    entries = [
        FoodEntry(name=name, kcal=kcal, dt=_dt(dt_off), cycle_id=cycle.id)
        for (name, kcal, dt_off) in items
    ]
    session.add_all(entries)
    session.flush()
    return entries


def _add_exercises(session, cycle: Cycle, items):
    """
    Add multiple ExerciseEntry rows for a given cycle.

    items: iterable of tuples (name, kcal, dt_offset_seconds)
    """
    entries = [
        ExerciseEntry(name=name, kcal=kcal, dt=_dt(dt_off), cycle_id=cycle.id)
        for (name, kcal, dt_off) in items
    ]
    session.add_all(entries)
    session.flush()
    return entries


# -----------------------
# Schema & lifecycle
# -----------------------


def test_init_database_creates_schema(db):
    """The database initializer must create the expected tables."""
    engine, _ = db
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert {"cycle", "food", "exercise"} <= tables


def test_create_cycle_and_read_current(session_factory):
    """Creating a cycle should make it the current open cycle (end_dt is NULL)."""
    session = session_factory()
    c = Cycle(start_dt=_dt())
    create_cycle(session, c)
    found = read_current_cycle(session)
    assert found is not None
    assert found.id == c.id
    assert found.end_dt is None


def test_only_one_open_cycle_enforced(session_factory):
    """Attempting to open a second cycle while one is open should raise."""
    c1 = Cycle(start_dt=_dt())
    session = session_factory()
    create_cycle(session, c1)
    c1_id = c1.id
    session.commit()

    session = session_factory()
    c2 = Cycle(start_dt=_dt(1))
    with pytest.raises(Cycle.CannotCreate):
        create_cycle(session, c2)

    session = session_factory()
    assert read_current_cycle(session).id == c1_id


def test_close_current_cycle_then_open_new(session_factory):
    """Closing the current cycle should allow a new open cycle to be created."""
    session = session_factory()
    c1 = _open_cycle(session)

    closed = close_current_cycle(session)
    session.flush()
    assert closed is not None
    assert closed.end_dt is not None

    c2 = Cycle(start_dt=_dt(2))
    create_cycle(session, c2)
    assert read_current_cycle(session).id == c2.id

    all_cycles = read_all_cycles(session)
    assert {c.id for c in all_cycles} == {c1.id, c2.id}


def test_close_when_non_open(session_factory):
    """Calling close when no cycle is open should return None (no-op)."""
    session = session_factory()
    _open_cycle(session)
    closed = close_current_cycle(session)
    assert closed is not None
    session.flush()

    session = session_factory()
    closed = close_current_cycle(session)
    assert closed is None


# -----------------------
# Entries (food & exercise)
# -----------------------


def test_create_food_entry_requires_open_cycle(session_factory):
    """Food entries require an open cycle; otherwise raise Cycle.NoOpenCycle."""
    entry = FoodEntry(name="Apple", kcal=95, dt=_dt())
    session = session_factory()
    with pytest.raises(Cycle.NoOpenCycle):
        create_food_entry(session, entry)

    session = session_factory()
    c = _open_cycle(session)
    entry_ok = create_food_entry(session, FoodEntry(name="Banana", kcal=105, dt=_dt()))
    assert entry_ok.id is not None
    assert entry_ok.cycle_id == c.id
    assert c.food_entries == sorted(c.food_entries, key=lambda e: e.dt)


def test_create_exercise_entry_requires_open_cycle(session_factory):
    """Exercise entries require an open cycle; otherwise raise Cycle.NoOpenCycle."""
    e = ExerciseEntry(name="Run", kcal=300, dt=_dt())
    session = session_factory()
    with pytest.raises(Cycle.NoOpenCycle):
        create_exercise_entry(session, e)

    session = session_factory()
    c = _open_cycle(session)
    e_ok = create_exercise_entry(
        session, ExerciseEntry(name="Swim", kcal=250, dt=_dt())
    )
    assert e_ok.id is not None
    assert e_ok.cycle_id == c.id
    assert c.exercise_entries == sorted(c.exercise_entries, key=lambda x: x.dt)


def test_remove_food_entry(session_factory):
    """Removing a specific food entry should leave other entries intact."""
    session = session_factory()
    c = _open_cycle(session)
    e1 = create_food_entry(session, FoodEntry(name="Yogurt", kcal=150, dt=_dt()))
    e2 = create_food_entry(session, FoodEntry(name="Toast", kcal=120, dt=_dt(1)))
    session.flush()
    e1_id = e1.id

    remove_food_entry(session, e1)
    session.flush()
    session.refresh(c)

    remaining = {fe.id for fe in c.food_entries}
    assert e1_id not in remaining
    assert e2.id in remaining


def test_remove_food_entry_by_id(session_factory):
    """Removing a specific food entry by id should leave other entries intact."""
    session = session_factory()
    c = _open_cycle(session)
    e1 = create_food_entry(session, FoodEntry(name="Yogurt", kcal=150, dt=_dt()))
    e2 = create_food_entry(session, FoodEntry(name="Toast", kcal=120, dt=_dt(1)))
    session.flush()
    e1_id = e1.id

    remove_food_entry_by_id(session, e1_id)
    session.flush()
    session.refresh(c)

    remaining = {fe.id for fe in c.food_entries}
    assert e1_id not in remaining
    assert e2.id in remaining


def test_remove_exercise_entry(session_factory):
    """Removing a specific exercise entry should leave other entries intact."""
    session = session_factory()
    c = _open_cycle(session)
    e1 = create_exercise_entry(session, ExerciseEntry(name="Bike", kcal=200, dt=_dt()))
    e2 = create_exercise_entry(session, ExerciseEntry(name="Row", kcal=220, dt=_dt(1)))
    session.flush()
    e1_id = e1.id

    remove_exercise_entry(session, e1)
    session.flush()
    session.refresh(c)

    remaining = {ee.id for ee in c.exercise_entries}
    assert e1_id not in remaining
    assert e2.id in remaining


def test_remove_exercise_by_id_entry(session_factory):
    """Removing a specific exercise entry by id should leave other entries intact."""
    session = session_factory()
    c = _open_cycle(session)
    e1 = create_exercise_entry(session, ExerciseEntry(name="Bike", kcal=200, dt=_dt()))
    e2 = create_exercise_entry(session, ExerciseEntry(name="Row", kcal=220, dt=_dt(1)))
    session.flush()
    e1_id = e1.id

    remove_exercise_entry_by_id(session, e1_id)
    session.flush()
    session.refresh(c)

    remaining = {ee.id for ee in c.exercise_entries}
    assert e1_id not in remaining
    assert e2.id in remaining


def test_food_kcal_non_negative_constraint(session_factory):
    """FoodEntry.kcal must be non-negative at the DB layer (CHECK constraint)."""
    session = session_factory()
    _open_cycle(session)
    bad = FoodEntry(name="???", kcal=-1, dt=_dt())
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_exercise_kcal_non_negative_constraint(session_factory):
    """ExerciseEntry.kcal must be non-negative at the DB layer (CHECK constraint)."""
    session = session_factory()
    _open_cycle(session)
    bad = ExerciseEntry(name="???", kcal=-5, dt=_dt())
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


@pytest.mark.parametrize("maintenance_kcal", [0, -1, -100])
def test_cycle_maintenance_kcal_constraint(session_factory, maintenance_kcal):
    """Cycle.maintenance_kcal must be positive; invalid values should fail at flush."""
    session = session_factory()
    bad_cycle = Cycle(start_dt=_dt(), maintenance_kcal=maintenance_kcal)
    session.add(bad_cycle)
    with pytest.raises(IntegrityError):
        session.flush()


def test_cascade_delete_cycle_removes_entries(session_factory):
    """Deleting a cycle should cascade-delete its food and exercise entries."""
    session = session_factory()
    c = _open_cycle(session)
    f1 = create_food_entry(session, FoodEntry(name="Eggs", kcal=140, dt=_dt()))
    x1 = create_exercise_entry(session, ExerciseEntry(name="Walk", kcal=100, dt=_dt()))

    session.delete(c)
    session.flush()

    session.expunge_all()
    assert session.get(FoodEntry, f1.id) is None
    assert session.get(ExerciseEntry, x1.id) is None


def test_read_all_cycles(session_factory):
    """read_all_cycles should return all persisted cycles in the DB."""
    session = session_factory()
    assert read_all_cycles(session) == []  # empty initially

    c1 = _open_cycle(session)
    close_current_cycle(session)
    session.flush()

    c2 = Cycle(start_dt=_dt(2))
    create_cycle(session, c2)

    allc = read_all_cycles(session)
    assert {c.id for c in allc} == {c1.id, c2.id}


# -----------------------
# Current cycle totals
# -----------------------


def test_current_cycle_raises_when_none_open(session_factory):
    """Aggregations for the current cycle should raise when no cycle is open."""
    session = session_factory()
    with pytest.raises(Cycle.NoOpenCycle):
        get_total_food_calories_current_cycle(session)

    session = session_factory()
    with pytest.raises(Cycle.NoOpenCycle):
        get_total_exercise_calories_current_cycle(session)


def test_current_cycle_sums_all_entries(session_factory):
    """Current cycle totals should sum all entries in that open cycle."""
    session = session_factory()
    c = _open_cycle(session)

    _add_foods(session, c, [("A", 100, 1), ("B", 250, 2), ("C", 150, 3)])
    _add_exercises(session, c, [("A", 100, 1), ("B", 250, 2), ("C", 150, 3)])

    total_food = get_total_food_calories_current_cycle(session)
    total_exercise = get_total_exercise_calories_current_cycle(session)

    assert total_food == 100 + 250 + 150
    assert total_exercise == 100 + 250 + 150


def test_current_cycle_ignores_closed_cycles(session_factory):
    """Current cycle totals must ignore entries from closed cycles."""
    session = session_factory()

    # Closed cycle with entries
    c1 = _open_cycle(session)
    _add_foods(session, c1, [("X", 300, 1)])
    _add_exercises(session, c1, [("X", 300, 1)])
    close_current_cycle(session)
    session.flush()

    # New open cycle with entries
    c2 = _open_cycle(session)
    _add_foods(session, c2, [("Y", 200, 3), ("Z", 50, 4)])
    _add_exercises(session, c2, [("Y", 200, 3), ("Z", 50, 4)])

    total_food = get_total_food_calories_current_cycle(session)
    total_exercise = get_total_exercise_calories_current_cycle(session)

    assert total_food == 200 + 50
    assert total_exercise == 200 + 50


# -----------------------
# Period totals
# -----------------------


def test_period_returns_zero_when_no_cycles_in_range(session_factory):
    """If no cycles start within [start, end), period totals should be zero."""
    session = session_factory()

    c = _open_cycle(session, start_offset=-1000)
    _add_foods(session, c, [("A", 999, -999)])
    _add_exercises(session, c, [("A", 999, -999)])
    close_current_cycle(session)
    session.flush()

    start = _dt(0)  # later than c.start_dt
    end = _dt(10)
    total_food = get_total_food_calories_for_period(session, start, end)
    total_exercise = get_total_exercise_calories_for_period(session, start, end)

    assert total_food == 0
    assert total_exercise == 0


def test_period_includes_single_closed_cycle_in_range(session_factory):
    """A single closed cycle whose start/end fall in range should be fully summed."""
    session = session_factory()

    c = _open_cycle(session, start_offset=0)
    _add_foods(session, c, [("A", 120, 1), ("B", 80, 2)])
    _add_exercises(session, c, [("A", 120, 1), ("B", 80, 2)])
    close_current_cycle(session)
    session.flush()
    session.refresh(c)

    start = c.start_dt
    end = c.end_dt
    total_food = get_total_food_calories_for_period(session, start, end)
    total_exercise = get_total_exercise_calories_for_period(session, start, end)

    assert total_food == 120 + 80
    assert total_exercise == 120 + 80


def test_period_includes_multiple_closed_cycles_and_sums(session_factory):
    """Multiple closed cycles in range should have their totals aggregated."""
    session = session_factory()

    c1 = _open_cycle(session, start_offset=0)
    _add_foods(session, c1, [("A1", 100, 1)])
    _add_exercises(session, c1, [("A1", 100, 1)])
    close_current_cycle(session)
    session.flush()
    session.refresh(c1)

    c2 = _open_cycle(session, start_offset=10)
    _add_foods(session, c2, [("A2", 200, 11), ("A3", 50, 12)])
    _add_exercises(session, c2, [("A2", 200, 11), ("A3", 50, 12)])
    close_current_cycle(session)
    session.flush()
    session.refresh(c2)

    start = min(c1.start_dt, c2.start_dt)
    end = max(c1.end_dt, c2.end_dt)
    total_food = get_total_food_calories_for_period(session, start, end)
    total_exercise = get_total_exercise_calories_for_period(session, start, end)

    assert total_food == 100 + 200 + 50
    assert total_exercise == 100 + 200 + 50


def test_period_includes_open_cycle_due_to_null_end_dt(session_factory):
    """
    When end_dt is NULL (open cycle), inclusion is based on start bound only;
    end bound is ignored for the open cycle.
    """
    session = session_factory()

    c_closed = _open_cycle(session, start_offset=0)
    _add_foods(session, c_closed, [("Closed", 75, 1)])
    _add_exercises(session, c_closed, [("Closed", 75, 1)])
    close_current_cycle(session)
    session.flush()
    session.refresh(c_closed)

    c_open = _open_cycle(session, start_offset=2)
    _add_foods(session, c_open, [("Open1", 500, 3), ("Open2", 25, 4)])
    _add_exercises(session, c_open, [("Open1", 500, 3), ("Open2", 25, 4)])
    session.flush()

    start = min(c_closed.start_dt, c_open.start_dt)
    end = _dt(5)  # arbitrary; open cycle passes due to end_dt IS NULL
    total_food = get_total_food_calories_for_period(session, start, end)
    total_exercise = get_total_exercise_calories_for_period(session, start, end)

    assert total_food == 75 + 500 + 25
    assert total_exercise == 75 + 500 + 25


def test_period_ignores_entry_timestamps_and_sums_whole_cycles(session_factory):
    """
    Period totals are based on cycle membership, not per-entry timestamps;
    once a cycle is included, all its entries are counted.
    """
    session = session_factory()

    c = _open_cycle(session, start_offset=0)
    _add_foods(session, c, [("E1", 10, -1), ("E2", 20, 999)])
    _add_exercises(session, c, [("E1", 10, -1), ("E2", 20, 999)])
    close_current_cycle(session)
    session.flush()
    session.refresh(c)

    start = c.start_dt
    end = c.end_dt
    total_food = get_total_food_calories_for_period(session, start, end)
    total_exercise = get_total_exercise_calories_for_period(session, start, end)

    assert total_food == 30
    assert total_exercise == 30


# -----------------------
# get_cycle_containing_datetime
# -----------------------


def test_cycle_containing_datetime_none_when_no_cycles(session_factory):
    """With no cycles in the DB, lookup should return None."""
    session = session_factory()
    dt = _dt(0)
    assert get_cycle_containing_datetime(session, dt) is None


def test_cycle_containing_datetime_in_closed_cycle_inclusive_start_exclusive_end(
    session_factory,
):
    """
    For a closed cycle [start, end), the start is inclusive and the end is exclusive.
    """
    session = session_factory()

    start = _dt(0)
    c = Cycle(start_dt=start)
    create_cycle(session, c)

    end = _dt(10)
    c.end_dt = end
    session.flush()
    session.refresh(c)

    mid = start + timedelta(seconds=5)
    assert get_cycle_containing_datetime(session, mid).id == c.id
    assert get_cycle_containing_datetime(session, start).id == c.id
    assert get_cycle_containing_datetime(session, end) is None  # exclusive upper bound


def test_cycle_containing_datetime_in_open_cycle(session_factory):
    """For an open cycle [start, ∞), start is inclusive and later times are contained."""
    session = session_factory()
    start = _dt(0)
    c_open = Cycle(start_dt=start)
    create_cycle(session, c_open)
    session.flush()
    session.refresh(c_open)

    dt_inside = start + timedelta(seconds=5)
    found = get_cycle_containing_datetime(session, dt_inside)
    assert found is not None and found.id == c_open.id
    assert get_cycle_containing_datetime(session, start).id == c_open.id


def test_cycle_containing_datetime_picks_correct_from_multiple_closed(session_factory):
    """When multiple closed cycles exist, lookup should return the correct containing one."""
    session = session_factory()

    t0 = _dt(0)
    c1 = Cycle(start_dt=t0)
    create_cycle(session, c1)
    c1.end_dt = _dt(10)
    session.flush()
    session.refresh(c1)

    c2 = Cycle(start_dt=_dt(20))
    create_cycle(session, c2)
    c2.end_dt = _dt(30)
    session.flush()
    session.refresh(c2)

    dt1 = t0 + timedelta(seconds=3)
    assert get_cycle_containing_datetime(session, dt1).id == c1.id

    dt2 = t0 + timedelta(seconds=25)
    assert get_cycle_containing_datetime(session, dt2).id == c2.id


def test_cycle_containing_datetime_outside_bounds_returns_none(session_factory):
    """Times before the start or at/after the exclusive end should return None."""
    session = session_factory()

    t0 = _dt(0).replace(microsecond=0)
    c = Cycle(start_dt=t0)
    create_cycle(session, c)
    c.end_dt = t0 + timedelta(seconds=10)
    session.flush()
    session.refresh(c)

    assert get_cycle_containing_datetime(session, t0 - timedelta(seconds=1)) is None
    assert get_cycle_containing_datetime(session, t0 + timedelta(seconds=10)) is None
    assert get_cycle_containing_datetime(session, t0 + timedelta(seconds=11)) is None


def test_cycle_containing_datetime_handoff_at_boundary(session_factory):
    """
    With exclusive end and inclusive start, a dt exactly equal to c1.end_dt == c2.start_dt
    should return c2 (handoff behavior).
    """
    session = session_factory()
    t0 = _dt(0)

    c1 = Cycle(start_dt=t0)
    create_cycle(session, c1)
    boundary = t0 + timedelta(seconds=10)
    c1.end_dt = boundary
    session.flush()
    session.refresh(c1)

    c2 = Cycle(start_dt=boundary)
    create_cycle(session, c2)
    c2.end_dt = boundary + timedelta(seconds=10)
    session.flush()
    session.refresh(c2)

    found = get_cycle_containing_datetime(session, boundary)
    assert found is not None and found.id == c2.id
    assert (
        get_cycle_containing_datetime(session, boundary - timedelta(milliseconds=1)).id
        == c1.id
    )


def test_cycle_containing_datetime_handles_gap_and_then_open_cycle(session_factory):
    """
    If there's a gap between a closed cycle and a later open cycle:
    - datetimes in the gap should return None
    - datetimes in the open cycle should return that open cycle
    """
    session = session_factory()

    t0 = _dt(0)
    c_closed = Cycle(start_dt=t0)
    create_cycle(session, c_closed)
    c_closed.end_dt = _dt(10)
    session.flush()
    session.refresh(c_closed)

    c_open = Cycle(start_dt=_dt(15))  # 5-second gap after closed cycle
    create_cycle(session, c_open)
    session.flush()
    session.refresh(c_open)

    assert get_cycle_containing_datetime(session, _dt(12)) is None
    assert get_cycle_containing_datetime(session, _dt(16)).id == c_open.id


# -----------------------
# Update entry functions
# -----------------------


def test_update_food_entry_persists_changes_and_keeps_cycle(session_factory):
    """
    update_food_entry should:
    - update name/kcal/dt in-place for the targeted row,
    - persist changes to the DB on flush/commit,
    - keep the original cycle_id unchanged.
    """
    session = session_factory()
    _open_cycle(session)
    original = create_food_entry(session, FoodEntry(name="Old", kcal=100, dt=_dt(10)))
    session.flush()
    original_id, original_cycle = original.id, original.cycle_id

    # Perform update with new values
    updated_data = FoodEntry(name="New", kcal=250, dt=_dt(20))
    ret = update_food_entry(session, original_id, updated_data)

    # Flush and re-read from DB to ensure persistence (not just in-memory)
    session.flush()
    session.expunge_all()
    persisted = session.get(FoodEntry, original_id)

    assert ret.id == original_id
    assert persisted is not None
    assert persisted.name == "New"
    assert persisted.kcal == 250
    assert persisted.dt == updated_data.dt
    # Cycle membership must not change
    assert persisted.cycle_id == original_cycle


def test_update_food_entry_not_found_raises(session_factory):
    """update_food_entry should raise EntryNotFound for an unknown id."""
    session = session_factory()
    _open_cycle(session)
    phantom_id = 999999
    with pytest.raises(EntryNotFound) as ei:
        update_food_entry(session, phantom_id, FoodEntry(name="X", kcal=1, dt=_dt()))
    # Don’t rely on exact wording; just sanity-check the message references the id.
    assert str(phantom_id) in str(ei.value)


def test_update_exercise_entry_persists_changes_and_keeps_cycle(session_factory):
    """
    update_exercise_entry should:
    - update name/kcal/dt in-place for the targeted row,
    - persist changes to the DB on flush/commit,
    - keep the original cycle_id unchanged.
    """
    session = session_factory()
    _open_cycle(session)
    original = create_exercise_entry(
        session, ExerciseEntry(name="OldEx", kcal=300, dt=_dt(10))
    )
    session.flush()
    original_id, original_cycle = original.id, original.cycle_id

    # Perform update with new values
    updated_data = ExerciseEntry(name="NewEx", kcal=450, dt=_dt(20))
    ret = update_exercise_entry(session, original_id, updated_data)

    # Flush and re-read from DB to ensure persistence
    session.flush()
    session.expunge_all()
    persisted = session.get(ExerciseEntry, original_id)

    assert ret.id == original_id
    assert persisted is not None
    assert persisted.name == "NewEx"
    assert persisted.kcal == 450
    assert persisted.dt == updated_data.dt
    # Cycle membership must not change
    assert persisted.cycle_id == original_cycle


def test_update_exercise_entry_not_found_raises(session_factory):
    """update_exercise_entry should raise EntryNotFound for an unknown id."""
    session = session_factory()
    _open_cycle(session)
    phantom_id = 888888
    with pytest.raises(EntryNotFound) as ei:
        update_exercise_entry(
            session, phantom_id, ExerciseEntry(name="Y", kcal=1, dt=_dt())
        )
    # Message sanity: should reference the id (note: function’s message says 'food_entry')
    assert str(phantom_id) in str(ei.value)
