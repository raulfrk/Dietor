import redis
from calories_tracker import ExerciseEntry, FoodEntry
import json

V1_APP_KEY = "calories_tracker_v1"
V2_APP_KEY = "calories_tracker_v2"


def v1_to_v2():
    food_entry_key = f"{V1_APP_KEY}/food_entries"
    obj_entry: list[FoodEntry] = []
    with redis.Redis(host="redis", port=6379) as r:
        entries = r.json().get(food_entry_key, "$")
        for e in entries[0]:
            dict_ent = json.loads(e)
            new_entry = FoodEntry(**dict_ent)
            obj_entry.append(new_entry)

        user_key = "6386583609"

        days = list(set([x.datetime.date() for x in obj_entry]))

        for day in days:
            days_key = f"{V2_APP_KEY}/{user_key}/days"

            if not r.exists(days_key):
                r.rpush(days_key, day.strftime("%Y%m%d"))

            entries_for_day = [x for x in obj_entry if x.datetime.date() == day]

            exercise_entires = [
                ExerciseEntry(datetime=x.datetime, kcal=x.kcal)
                for x in entries_for_day
                if "exercise" in x.food_name.lower()
            ]
            exercise_entires_dict = [x.model_dump_json() for x in exercise_entires]

            food_entries = [x for x in entries_for_day if x not in exercise_entires]
            food_entries_dict = [x.model_dump_json() for x in food_entries]

            food_entries_key = f"{V2_APP_KEY}/{user_key}/{day}/food_entries"
            exercise_entries_key = f"{V2_APP_KEY}/{user_key}/{day}/exercise_entries"
            r.json().set(food_entries_key, "$", food_entries_dict)
            r.json().set(exercise_entries_key, "$", exercise_entires_dict)


v1_to_v2()
