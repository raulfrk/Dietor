from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from diet_tracker.data.table_helpers import (
    get_exercise_entries_for_period,
    get_food_entries_for_period,
    read_current_cycle,
)
from diet_tracker.data.tables import ExerciseEntry, FoodEntry, init_database


@dataclass
class DailyStats:
    food_entries: list[FoodEntry]
    exercise_entries: list[ExerciseEntry]
    kcal_in: int
    kcal_out: int
    maintenance: int
    deficit: int
    deficit_goal: int
    dt: date
    empty: bool

    def pretty_print(self) -> str:  # pragma: no cover

        if self.empty:
            return "No in/out calories recorded for this day."
        nice_string = "Food entries:\n"
        for fe in self.food_entries:
            nice_string += f"({fe.id}) {fe.name} - {fe.kcal} kcal\n"
        nice_string += "\n\nExercise entries:\n" if self.exercise_entries else ""
        for e in self.exercise_entries:
            nice_string += f"({e.id}) {e.name} - {e.kcal} kcal\n"

        nice_string += "\n\n"
        nice_string += f"Maintenance: {self.maintenance}\n"
        nice_string += f"In VS Out: {self.kcal_in} kcal vs {self.kcal_out} kcal\n"
        nice_string += (
            f"{'Surplus' if self.deficit < 0 else 'Deficit'}: {abs(self.deficit)}\n"
        )
        nice_string += f"Deficit vs Deficit Goal: {self.deficit}/{self.deficit_goal}"

        return nice_string


@dataclass
class PeriodDailyStats:
    daily_stats: list[DailyStats]
    kcal_in: int
    kcal_out: int
    maintenance: int
    deficit: int
    deficit_incl_today: int
    deficit_goal: int
    start_dt: date
    end_dt: date

    def pretty_print(self, full: bool = False) -> str:  # pragma: no cover
        nice_string = ""

        full_out_string = ""

        if full:
            full_out_string += "Daily breakdown\n"
            for ds in self.daily_stats:
                full_out_string += "_" * 20 + "\n->" + ds.dt.strftime("%Y-%m-%d") + "\n"
                full_out_string += ds.pretty_print() + "\n" + "_" * 20 + "\n\n"

            full_out_string += "Period summary: "
            nice_string += full_out_string
        nice_string += f"Maintenance: {self.maintenance}\n"
        nice_string += f"In VS Out: {self.kcal_in} kcal vs {self.kcal_out} kcal\n"
        nice_string += (
            f"{'Surplus' if self.deficit < 0 else 'Deficit'}: {abs(self.deficit)}\n\n"
        )
        nice_string += (
            f"Deficit vs Deficit Goal: {self.deficit}/{self.deficit_goal}"
            f" (excluding today equals to {len(self.daily_stats)-1} days)\n\n"
        )
        nice_string += (
            f"Deficit vs Deficit Goal: {self.deficit_incl_today}/"
            f"{self.deficit_goal} (including today equals to "
            f"{len(self.daily_stats)} days)\n"
        )

        return nice_string


def round_sod(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def round_eod(dt: datetime) -> datetime:
    return dt.replace(hour=23, minute=59, second=59, microsecond=0)


def get_daily_stats(user_id: str, path: Path, datetime: datetime) -> DailyStats | None:

    _, SessionLocal = init_database(user_id=user_id, path=path)
    day_start = round_sod(datetime)
    day_end = round_eod(datetime)
    with SessionLocal.begin() as session:
        food_entries = get_food_entries_for_period(session, day_start, day_end)
        exercise_enties = get_exercise_entries_for_period(session, day_start, day_end)
        one_cycle = None
        if len(food_entries) != 0:
            one_cycle = food_entries[-1].cycle
        else:
            one_cycle = read_current_cycle(session)
            if one_cycle is None:
                return None

        filtered_food_entries = [x for x in food_entries if x.cycle_id == one_cycle.id]
        filtered_exercise_entries = [
            x for x in exercise_enties if x.cycle_id == one_cycle.id
        ]

        kcal_in = sum(x.kcal for x in filtered_food_entries)
        kcal_out = sum(x.kcal for x in filtered_exercise_entries)

        if kcal_in == 0 and kcal_out == 0:
            return DailyStats([], [], 0, 0, 0, 0, 0, day_start.date(), empty=True)

        session.expunge_all()

        return DailyStats(
            filtered_food_entries,
            filtered_exercise_entries,
            kcal_in,
            kcal_out,
            one_cycle.maintenance_kcal,
            one_cycle.maintenance_kcal - (kcal_in - kcal_out),
            one_cycle.daily_deficit_goal,
            day_start.date(),
            False,
        )


def get_daily_stats_period(
    user_id: str, path: Path, start_dt: datetime, end_dt: datetime
) -> PeriodDailyStats:

    in_between_dates = []

    rounded_start = round_sod(start_dt)

    while rounded_start <= end_dt:
        in_between_dates.append(round_sod(rounded_start))

        rounded_start += timedelta(days=1)

    daily_stats_w_none = [get_daily_stats(user_id, path, x) for x in in_between_dates]
    daily_stats = [x for x in daily_stats_w_none if x is not None]

    # Filter out days where it was not tracked
    daily_stats = [x for x in daily_stats if not x.empty]

    total_kcal_in = sum([x.kcal_in for x in daily_stats])
    total_kcal_out = sum([x.kcal_out for x in daily_stats])
    total_maintenance = sum([x.maintenance for x in daily_stats])
    daily_stats_no_today = [x for x in daily_stats if x.dt != datetime.now().date()]
    total_deficit = sum([x.deficit for x in daily_stats_no_today])
    total_deficit_incl_today = sum([x.deficit for x in daily_stats])
    total_deficit_goal = sum([x.deficit_goal for x in daily_stats])

    return PeriodDailyStats(
        daily_stats,
        total_kcal_in,
        total_kcal_out,
        total_maintenance,
        total_deficit,
        total_deficit_incl_today,
        total_deficit_goal,
        in_between_dates[0].date(),
        in_between_dates[-1].date(),
    )
