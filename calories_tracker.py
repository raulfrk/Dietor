# from unittest.mock import Base
import redis

# from pydantic import BaseModel
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import json
from redis.commands.json.path import Path
from telegram import BotCommand

from data.calories_tracker.food import (
    ExerciseEntry,
    FoodEntry,
    add_food_exercise_entry,
    get_day_full_summary,
    remove_entry_by_id,
)

APP_KEY = "calories_tracker_v2"
TOKEN = "7880093755:AAEOoaxDxuvRfjwYQB-leeeMPvX_2s-SwEI"
ALLOWED_USER = 6386583609


# class FoodEntry(BaseModel):
#     datetime: datetime
#     food_name: str
#     kcal: int


# class ExerciseEntry(BaseModel):
#     datetime: datetime
#     kcal: int


def format_food_entry_list(ls: list[FoodEntry]) -> str:
    final_string = ""
    for i, e in enumerate(ls):
        formatted_dt = e.datetime.strftime("%Y/%m/%d")
        entry = f"[{i}] - {str(formatted_dt)}\n{e.food_name}: {e.kcal}kcal\n\n"
        final_string += entry
    return final_string


def add_food_entry(entry: FoodEntry):
    food_entry_key = f"{APP_KEY}/food_entries"
    with redis.Redis(host="redis", port=6379) as r:
        if not r.exists(food_entry_key):
            r.json().set(food_entry_key, "$", [])
        json_dump = entry.model_dump_json()
        r.json().arrappend(food_entry_key, "$", json_dump)


def remove_food_entry(idx: int):
    food_entry_key = f"{APP_KEY}/food_entries"
    with redis.Redis(host="redis", port=6379) as r:
        r.json().delete(food_entry_key, Path(f"$[{idx}]"))


def get_food_entries():
    food_entry_key = f"{APP_KEY}/food_entries"
    obj_entry = []
    with redis.Redis(host="redis", port=6379) as r:
        entries = r.json().get(food_entry_key, "$")
        for e in entries[0]:
            dict_ent = json.loads(e)
            new_entry = FoodEntry(**dict_ent)
            obj_entry.append(new_entry)
    return obj_entry


async def restricted(update: Update) -> bool:
    user_id = update.effective_user.id
    return user_id == ALLOWED_USER


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restricted(update):
        await update.message.reply_text("Unauthorized")
        return

    await update.message.reply_text("Hello! I am your dietor bot.")


async def remove_today_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restricted(update):
        await update.message.reply_text("Unauthorized.")
        return

    # Expect at least 2 arguments: food_name and kcal
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /removeex {idx}")
        return

    idx_str = context.args[0]

    try:
        idx = int(idx_str)
    except ValueError:
        await update.message.reply_text("Index must be a number.")
        return

    remove_entry_by_id(update.effective_user.id, datetime.now(), idx, False)
    food_list = get_day_full_summary(datetime.now(), update.effective_user.id)
    await update.message.reply_text(food_list, parse_mode="MarkdownV2")


async def remove_today_food(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restricted(update):
        await update.message.reply_text("Unauthorized.")
        return

    # Expect at least 2 arguments: food_name and kcal
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /removefood {idx}")
        return

    idx_str = context.args[0]

    try:
        idx = int(idx_str)
    except ValueError:
        await update.message.reply_text("Index must be a number.")
        return

    remove_entry_by_id(update.effective_user.id, datetime.now(), idx, True)
    food_list = get_day_full_summary(datetime.now(), update.effective_user.id)
    await update.message.reply_text(food_list, parse_mode="MarkdownV2")


async def add_food_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restricted(update):
        await update.message.reply_text("Unauthorized.")
        return

    # Expect at least 2 arguments: food_name and kcal
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addfood {food_name} {kcal}")
        return

    food_name = " ".join(context.args[:-1])
    kcal_str = context.args[-1]

    try:
        kcal = int(kcal_str)
    except ValueError:
        await update.message.reply_text("Calories must be a number.")
        return

    fe = FoodEntry(datetime=datetime.now(), food_name=food_name, kcal=kcal, id=0)

    add_food_exercise_entry(update.effective_user.id, fe)
    food_list = get_day_full_summary(datetime.now(), update.effective_user.id)
    await update.message.reply_text(food_list, parse_mode="MarkdownV2")


async def add_exercise_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restricted(update):
        await update.message.reply_text("Unauthorized.")
        return

    # Expect at least 1 arguments: kcal
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /addex {kcal}")
        return
    kcal_str = context.args[-1]

    try:
        kcal = int(kcal_str)
    except ValueError:
        await update.message.reply_text("Calories must be a number.")
        return

    fe = ExerciseEntry(datetime=datetime.now(), kcal=kcal, id=0)

    add_food_exercise_entry(update.effective_user.id, fe)
    food_list = get_day_full_summary(datetime.now(), update.effective_user.id)
    await update.message.reply_text(food_list, parse_mode="MarkdownV2")


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restricted(update):
        await update.message.reply_text("Unauthorized.")
        return
    food_list = get_day_full_summary(datetime.now(), update.effective_user.id)
    await update.message.reply_text(food_list, parse_mode="MarkdownV2")


async def post_init(app):
    commands = [
        BotCommand("add", "Add a new meal"),
        BotCommand("get", "See all meal history"),
        BotCommand("remove", "Remove a meal"),
    ]
    await app.bot.set_my_commands(commands)


def main():
    # Create application
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    # Add a /start command
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addfood", add_food_today))
    app.add_handler(CommandHandler("addex", add_exercise_today))

    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("removefood", remove_today_food))
    app.add_handler(CommandHandler("removeex", remove_today_exercise))

    # Run the bot
    app.run_polling()


if __name__ == "__main__":
    main()
