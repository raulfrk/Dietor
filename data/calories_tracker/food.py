import json
from pydantic import BaseModel
from datetime import datetime, date
import redis
from data.calories_tracker.const import (
    APP_KEY,
    REDIS_HOST,
    REDIS_PORT,
    FOOD_ENTRIES_KEY,
    EXERCISE_ENTRIES_KEY,
)


class FoodEntry(BaseModel):
    id: int
    datetime: datetime
    food_name: str
    kcal: int


class ExerciseEntry(BaseModel):
    id: int
    datetime: datetime
    kcal: int


def add_food_exercise_entry(user_key: str, entry: FoodEntry | ExerciseEntry) -> None:
    entry_date = entry.datetime.date()
    entry_date_str = entry_date.strftime("%Y%m%d")

    # Choose key
    if isinstance(entry, FoodEntry):
        app_key = f"{APP_KEY}/{user_key}/{FOOD_ENTRIES_KEY}/{entry_date_str}"
    else:
        app_key = f"{APP_KEY}/{user_key}/{EXERCISE_ENTRIES_KEY}/{entry_date_str}"

    entries_days = f"{app_key}/days"

    with redis.Redis(REDIS_HOST, REDIS_PORT) as r:
        # Ensure the JSON array exists
        if not r.exists(app_key):
            r.json().set(app_key, "$", [])

        # Track which days have entries
        if r.lpos(entries_days, entry_date_str) is None:
            r.rpush(entries_days, entry_date_str)

        # Assign new id
        entry.id = r.json().arrlen(app_key, "$").pop()

        # Dump entry (convert datetime to str automatically)
        entry_dump = json.loads(entry.model_dump_json())

        # Append entry
        r.json().arrappend(app_key, "$", entry_dump)


def get_entries_for_day(
    user_key: str, date: date
) -> tuple[list[FoodEntry], list[ExerciseEntry]]:
    entry_date_str = date.strftime("%Y%m%d")
    food_entries_key = f"{APP_KEY}/{user_key}/{FOOD_ENTRIES_KEY}/{entry_date_str}"
    exercise_entries_key = (
        f"{APP_KEY}/{user_key}/{EXERCISE_ENTRIES_KEY}/{entry_date_str}"
    )

    with redis.Redis(REDIS_HOST, REDIS_PORT) as r:
        food_entries = r.json().get(food_entries_key, "$")
        exercise_entries = r.json().get(exercise_entries_key, "$")

        food_entries = food_entries[0] if food_entries is not None else []
        exercise_entries = exercise_entries[0] if exercise_entries is not None else []

        # Convert datetime strings back to datetime
        food_entries_objs = []
        exercise_entries_objs = []

        for e in food_entries:
            e["datetime"] = datetime.fromisoformat(e["datetime"])
            food_entries_objs.append(FoodEntry(**e))

        for e in exercise_entries:
            e["datetime"] = datetime.fromisoformat(e["datetime"])
            exercise_entries_objs.append(ExerciseEntry(**e))

    # Sort by kcal
    food_entries_objs.sort(key=lambda x: x.kcal)
    exercise_entries_objs.sort(key=lambda x: x.kcal)

    return food_entries_objs, exercise_entries_objs


def get_day_full_summary(date: datetime, user_key: str) -> str:
    sorted_food, sorted_exercise = get_entries_for_day(user_key, date)
    if not sorted_food and not sorted_exercise:
        return f"**{date.strftime('%Y%m%d')}**\n\nNo entries\\."

    # Determine date label (prefer food entries if present)
    dt = (
        sorted_food[-1].datetime if sorted_food else sorted_exercise[-1].datetime
    ).strftime("%Y%m%d")

    final_text = f"**{dt}**\n\nFood:\n"

    for f in sorted_food:
        final_text += f"[{f.id}] \\- {f.food_name}: {f.kcal}kcal\n\n"

    final_text += "Exercise:\n"
    for e in sorted_exercise:
        final_text += f"[{e.id}] \\- {e.kcal}kcal\n\n"

    total = sum(f.kcal for f in sorted_food) - sum(e.kcal for e in sorted_exercise)
    total = str(total).replace("-", "\\-")
    final_text += f"**Total: {total}**"

    return final_text


def remove_entry_by_id(user_key: str, date: datetime, entry_id: int, is_food=True):
    entry_date_str = date.strftime("%Y%m%d")
    if is_food:
        app_key = f"{APP_KEY}/{user_key}/{FOOD_ENTRIES_KEY}/{entry_date_str}"
    else:
        app_key = f"{APP_KEY}/{user_key}/{EXERCISE_ENTRIES_KEY}/{entry_date_str}"

    with redis.Redis(REDIS_HOST, REDIS_PORT) as r:
        # Get current entries
        entries = r.json().get(app_key, "$")
        if not entries:
            return  # Nothing to delete

        arr = entries[0]

        # Filter out entries with matching id
        filtered = [item for item in arr if item.get("id") != entry_id]

        # Replace the array with filtered version
        r.json().set(app_key, "$", filtered)
