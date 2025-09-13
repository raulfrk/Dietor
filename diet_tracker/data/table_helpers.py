from datetime import datetime, timezone

from sqlalchemy import (
    delete,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    Session,
)

from diet_tracker.data.tables import Cycle, EntryNotFound, ExerciseEntry, FoodEntry


def read_all_cycles(session: Session) -> list[Cycle]:
    return session.execute(select(Cycle)).scalars().all()


def read_current_cycle(session: Session) -> Cycle | None:
    return session.execute(
        select(Cycle).where(Cycle.end_dt.is_(None)).limit(2)
    ).scalar_one_or_none()


def create_cycle(session: Session, cycle: Cycle) -> Cycle:
    try:
        session.add(cycle)
        session.flush()
        session.refresh(cycle)
        return cycle
    except IntegrityError as e:
        raise Cycle.CannotCreate(
            "could not create cycle as a non-closed cycle exists. Close it and "
            "retry."
        ) from e


def close_current_cycle(session: Session) -> Cycle | None:
    current = read_current_cycle(session)

    if current is None:
        return current

    current.end_dt = datetime.now(timezone.utc)
    return current


def create_food_entry(session: Session, entry: FoodEntry) -> FoodEntry:
    current_cycle = read_current_cycle(session)

    if current_cycle is None:
        msg = f"could not add entry {entry}, no open cycle found."
        raise Cycle.NoOpenCycle(msg)

    current_cycle.food_entries.append(entry)
    session.flush()
    session.refresh(entry)
    return entry


def remove_food_entry(session: Session, entry: FoodEntry) -> None:
    session.delete(entry)


def remove_food_entry_by_id(session: Session, entry_id: int) -> int:
    stmt = delete(FoodEntry).where(FoodEntry.id == entry_id)
    return session.execute(stmt).rowcount


def remove_exercise_entry_by_id(session: Session, entry_id: int) -> int:
    stmt = delete(ExerciseEntry).where(ExerciseEntry.id == entry_id)
    return session.execute(stmt).rowcount


def update_food_entry(session: Session, entry_id: int, entry: FoodEntry) -> FoodEntry:

    stmt = select(FoodEntry).where(FoodEntry.id == entry_id)

    old_entry = session.execute(stmt).scalar_one_or_none()

    if old_entry is None:
        raise EntryNotFound(f"food_entry with id {entry_id} not found")

    old_entry.dt = entry.dt
    old_entry.name = entry.name
    old_entry.kcal = entry.kcal

    return old_entry


def update_exercise_entry(
    session: Session, entry_id: int, entry: ExerciseEntry
) -> ExerciseEntry:

    stmt = select(ExerciseEntry).where(ExerciseEntry.id == entry_id)

    old_entry = session.execute(stmt).scalar_one_or_none()

    if old_entry is None:
        raise EntryNotFound(f"food_entry with id {entry_id} not found")

    old_entry.dt = entry.dt
    old_entry.name = entry.name
    old_entry.kcal = entry.kcal

    return old_entry


def create_exercise_entry(session: Session, entry: ExerciseEntry) -> ExerciseEntry:
    current_cycle = read_current_cycle(session)

    if current_cycle is None:
        msg = f"could not add entry {entry}, no open cycle found."
        raise Cycle.NoOpenCycle(msg)

    current_cycle.exercise_entries.append(entry)
    session.flush()
    session.refresh(entry)
    return entry


def remove_exercise_entry(session: Session, entry: ExerciseEntry) -> None:
    session.delete(entry)


def get_total_food_calories_for_period(
    session: Session, start_dt: datetime, end_dt: datetime
) -> int:
    stmt = (
        select(func.coalesce(func.sum(FoodEntry.kcal), 0))
        .join(Cycle, FoodEntry.cycle_id == Cycle.id)
        .where(
            (Cycle.start_dt >= start_dt)
            & ((Cycle.end_dt <= end_dt) | (Cycle.end_dt.is_(None)))
        )
    )
    return session.execute(stmt).scalar_one()


def get_total_food_calories_current_cycle(session: Session) -> int:
    current_cycle = read_current_cycle(session)
    if current_cycle is None:
        raise Cycle.NoOpenCycle("no open cycle found")
    total_food_calories = 0

    total_food_calories += sum(entry.kcal for entry in current_cycle.food_entries)
    return total_food_calories


def get_total_exercise_calories_for_period(
    session: Session, start_dt: datetime, end_dt: datetime
) -> int:
    stmt = (
        select(func.coalesce(func.sum(ExerciseEntry.kcal), 0))
        .join(Cycle, ExerciseEntry.cycle_id == Cycle.id)
        .where(
            (Cycle.start_dt >= start_dt)
            & ((Cycle.end_dt <= end_dt) | (Cycle.end_dt.is_(None)))
        )
    )
    return session.execute(stmt).scalar_one()


def get_total_exercise_calories_current_cycle(session: Session) -> int:
    current_cycle = read_current_cycle(session)
    if current_cycle is None:
        raise Cycle.NoOpenCycle("no open cycle found")
    total_food_calories = 0

    total_food_calories += sum(entry.kcal for entry in current_cycle.exercise_entries)
    return total_food_calories


def get_cycle_containing_datetime(session: Session, dt: datetime) -> Cycle | None:
    stmt = select(Cycle).where(
        (Cycle.start_dt <= dt) & ((Cycle.end_dt > dt) | (Cycle.end_dt.is_(None)))
    )
    return session.execute(stmt).scalar_one_or_none()


def get_food_entries_for_period(
    session: Session, start_dt: datetime, end_dt: datetime
) -> list[FoodEntry]:
    stmt = (
        select(FoodEntry)
        .where((FoodEntry.dt >= start_dt) & (FoodEntry.dt <= end_dt))
        .order_by(FoodEntry.dt)
    )
    return session.execute(stmt).scalars().all()


def get_exercise_entries_for_period(
    session: Session, start_dt: datetime, end_dt: datetime
) -> list[ExerciseEntry]:
    stmt = (
        select(ExerciseEntry)
        .where((ExerciseEntry.dt >= start_dt) & (ExerciseEntry.dt <= end_dt))
        .order_by(ExerciseEntry.dt)
    )
    return session.execute(stmt).scalars().all()
