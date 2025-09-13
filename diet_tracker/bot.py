from datetime import datetime, timedelta
from enum import IntEnum, auto
from functools import partial
from pathlib import Path

from telegram import (
    BotCommand,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from diet_tracker.data.metrics import get_daily_stats, get_daily_stats_period
from diet_tracker.data.table_helpers import (
    close_current_cycle,
    create_cycle,
    create_exercise_entry,
    create_food_entry,
    read_current_cycle,
    remove_exercise_entry_by_id,
    remove_food_entry_by_id,
)
from diet_tracker.data.tables import Cycle, ExerciseEntry, FoodEntry, init_database

# from diet_tracker.data.tables import init_database


class States(IntEnum):
    # Cycle management
    # CREATE
    START_CREATE_CYCLE = auto()
    CREATE_CYCLE_MAINTENANCE = auto()
    CREATE_CYCLE_CONFIRM = auto()

    # CLOSE
    START_CLOSE_CURRENT_CYCLE = auto()
    CLOSE_CURRENT_CYCLE_CONFIRM = auto()

    # Food management
    # CREATE
    START_CREATE_FOOD_ENTRY = auto()
    CREATE_FOOD_ENTRY_NAME = auto()
    CREATE_FOOD_ENTRY_KCAL = auto()
    CREATE_FOOD_ENTRY_CONFIRM = auto()

    # DELETE
    START_DELETE_FOOD_ENTRY = auto()
    DELETE_FOOD_ENTRY_ID = auto()
    DELETE_FOOD_ENTRY_CONFIRM = auto()

    # Exercise management
    # CREATE
    START_CREATE_EXERCISE_ENTRY = auto()
    CREATE_EXERCISE_ENTRY_NAME = auto()
    CREATE_EXERCISE_ENTRY_KCAL = auto()
    CREATE_EXERCISE_ENTRY_CONFIRM = auto()

    # DELETE
    START_DELETE_EXERCISE_ENTRY = auto()
    DELETE_EXERCISE_ENTRY_ID = auto()
    DELETE_EXERCISE_ENTRY_CONFIRM = auto()


YESNO_KB = ReplyKeyboardMarkup(
    [["Yes", "No"]], resize_keyboard=True, one_time_keyboard=True
)


async def start_delete_food_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Select a food entry to delete:")
    await get_day_food_stats(update, context)
    await update.message.reply_text("ID: ")

    return States.DELETE_FOOD_ENTRY_ID


async def delete_food_entry_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    food_id = update.message.text
    if not food_id.isdigit():
        await update.message.reply_text("Please insert the id of a food entry.")
        return States.START_DELETE_FOOD_ENTRY
    await update.message.reply_text(
        f"Are you sure you want to try delete entry {food_id}?", reply_markup=YESNO_KB
    )
    context.user_data["entry_id"] = int(food_id)

    return States.DELETE_FOOD_ENTRY_CONFIRM


async def delete_food_entry_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.lower().startswith("y"):
        id = str(update.effective_user.id)
        entry_id = context.user_data["entry_id"]
        _, sessionMaker = init_database(id, Path("/data"))
        with sessionMaker.begin() as session:
            rows_deleted = remove_food_entry_by_id(session, entry_id)
        if rows_deleted == 0:
            await update.message.reply_text("No entry found to delete.")
            return ConversationHandler.END
        else:
            await update.message.reply_text("Entry deleted.")
            await get_day_food_stats(update, context)
            return ConversationHandler.END
    else:
        await update.message.reply_text("Cancelled.")
        return ConversationHandler.END


async def start_delete_exercise_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text("Select an exercise entry to delete:")
    await get_day_food_stats(update, context)
    await update.message.reply_text("ID: ")

    return States.DELETE_EXERCISE_ENTRY_ID


async def delete_exercise_entry_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exercise_id = update.message.text
    if not exercise_id.isdigit():
        await update.message.reply_text("Please insert the id of an exercise entry.")
        return States.START_DELETE_FOOD_ENTRY
    await update.message.reply_text(
        f"Are you sure you want to try delete entry {exercise_id}?",
        reply_markup=YESNO_KB,
    )
    context.user_data["entry_id"] = int(exercise_id)

    return States.DELETE_EXERCISE_ENTRY_CONFIRM


async def delete_exercise_entry_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if update.message.text.lower().startswith("y"):
        id = str(update.effective_user.id)
        entry_id = context.user_data["entry_id"]
        _, sessionMaker = init_database(id, Path("/data"))
        with sessionMaker.begin() as session:
            rows_deleted = remove_exercise_entry_by_id(session, entry_id)
        if rows_deleted == 0:
            await update.message.reply_text("No entry found to delete.")
            return ConversationHandler.END
        else:
            await update.message.reply_text("Entry deleted.")
            await get_day_food_stats(update, context)
            return ConversationHandler.END
    else:
        await update.message.reply_text("Cancelled.")
        return ConversationHandler.END


async def start_create_cycle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Starting a new cycle, please insert your maintenance calories."
    )
    return States.CREATE_CYCLE_MAINTENANCE


async def start_create_food_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Inserting new food entry, please insert the name for the entry."
    )
    return States.CREATE_FOOD_ENTRY_NAME


async def create_food_entry_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    food_name = update.message.text.strip()

    if food_name == "":
        await update.message.reply_text("Please insert a food name.")
        return States.START_CREATE_FOOD_ENTRY

    context.user_data["food_name"] = food_name
    await update.message.reply_text("Please insert a food kcal.")

    return States.CREATE_FOOD_ENTRY_KCAL


async def create_food_entry_kcal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kcal = update.message.text

    if not kcal.isdigit():
        await update.message.reply_text("Please insert number of kcal.")
        return States.CREATE_FOOD_ENTRY_KCAL

    context.user_data["food_kcal"] = kcal
    food_name = context.user_data["food_name"]

    await update.message.reply_text(
        f"Are you sure you want to add entry with name: {food_name}; kcal: {kcal}",
        reply_markup=YESNO_KB,
    )

    return States.CREATE_FOOD_ENTRY_CONFIRM


async def create_food_entry_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kcal = context.user_data["food_kcal"]
    food_name = context.user_data["food_name"]
    id = str(update.effective_user.id)
    if update.message.text.lower().startswith("y"):
        fe = FoodEntry(name=food_name, kcal=kcal)
        _, sessionMaker = init_database(id, Path("/data"))
        with sessionMaker.begin() as session:
            try:
                create_food_entry(session, fe)
            except Cycle.NoOpenCycle:
                await update.message.reply_text(
                    "No opened cycle, create a diet cycle first."
                )
                return ConversationHandler.END

        await update.message.reply_text("Food added.")
    else:
        await update.message.reply_text("Cancelled")
    await get_day_food_stats(update, context)

    return ConversationHandler.END


async def start_create_exercise_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "Inserting new exercise entry, please insert the name for the entry."
    )
    return States.CREATE_EXERCISE_ENTRY_NAME


async def create_exercise_entry_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    exercise_name = update.message.text.strip()

    if exercise_name == "":
        await update.message.reply_text("Please insert an exercise name.")
        return States.START_CREATE_EXERCISE_ENTRY

    context.user_data["exercise"] = exercise_name
    await update.message.reply_text("Please insert burnt kcal.")

    return States.CREATE_EXERCISE_ENTRY_KCAL


async def create_exercise_entry_kcal(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    kcal = update.message.text

    if not kcal.isdigit():
        await update.message.reply_text("Please insert number of kcal.")
        return States.CREATE_FOOD_ENTRY_KCAL

    context.user_data["exercise_kcal"] = kcal
    exercise_name = context.user_data["exercise"]

    await update.message.reply_text(
        f"Are you sure you want to add entry with name: {exercise_name}; kcal: {kcal}",
        reply_markup=YESNO_KB,
    )

    return States.CREATE_EXERCISE_ENTRY_CONFIRM


async def create_exercise_entry_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    kcal = context.user_data["exercise_kcal"]
    food_name = context.user_data["exercise"]
    id = str(update.effective_user.id)
    if update.message.text.lower().startswith("y"):
        fe = ExerciseEntry(name=food_name, kcal=kcal)
        _, sessionMaker = init_database(id, Path("/data"))
        with sessionMaker.begin() as session:
            try:
                create_exercise_entry(session, fe)
            except Cycle.NoOpenCycle:
                await update.message.reply_text(
                    "No opened cycle, create a diet cycle first."
                )
                return ConversationHandler.END

        await update.message.reply_text("Exercise added.")
    else:
        await update.message.reply_text("Cancelled")
    await get_day_food_stats(update, context)

    return ConversationHandler.END


async def get_day_food_stats(
    update: Update, context: ContextTypes.DEFAULT_TYPE, full: bool = False
):
    id = str(update.effective_user.id)
    daily_stats = get_daily_stats(id, Path("/data"), datetime.now())
    if daily_stats is None:
        await update.message.reply_text("No cycle found, create a cycle first.")
    else:
        await update.message.reply_text(daily_stats.pretty_print())


async def get_week_food_stats(
    update: Update, context: ContextTypes.DEFAULT_TYPE, full: bool = False
):
    id = str(update.effective_user.id)
    daily_stats = get_daily_stats_period(
        id, Path("/data"), datetime.now() - timedelta(days=6), datetime.now()
    )
    if daily_stats is None:
        await update.message.reply_text("No cycle found, create a cycle first.")
    else:
        await update.message.reply_text(daily_stats.pretty_print(full))


async def get_month_food_stats(
    update: Update, context: ContextTypes.DEFAULT_TYPE, full: bool = False
):
    id = str(update.effective_user.id)
    daily_stats = get_daily_stats_period(
        id, Path("/data"), datetime.now() - timedelta(days=29), datetime.now()
    )
    if daily_stats is None:
        await update.message.reply_text("No cycle found, create a cycle first.")
    else:
        await update.message.reply_text(daily_stats.pretty_print(full))


async def create_cycle_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    maintenance = update.message.text
    if not maintenance.isdigit():
        await update.message.reply_text("Please enter a number:")
        return States.CREATE_CYCLE_MAINTENANCE
    context.user_data["cycle_maintenance"] = int(update.message.text)

    await update.message.reply_text(
        f"Save: {context.user_data['cycle_maintenance']} kcal?", reply_markup=YESNO_KB
    )

    return States.CREATE_CYCLE_CONFIRM


async def create_cycle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    id = update.effective_user.id
    if update.message.text.lower().startswith("y"):
        _, sessionMaker = init_database(str(id), Path("/data"))
        with sessionMaker.begin() as session:
            new_cycle = Cycle(
                start_dt=datetime.now(),
                maintenance_kcal=context.user_data["cycle_maintenance"],
            )
            try:
                create_cycle(session, new_cycle)
            except Cycle.CannotCreate:
                await update.message.reply_text(
                    "An open cycle exists, would you like to close it?",
                    reply_markup=YESNO_KB,
                )
                context.user_data.clear()
                return States.CLOSE_CURRENT_CYCLE_CONFIRM

        await update.message.reply_text("Saved")
    else:
        await update.message.reply_text("Canceled")

    context.user_data.clear()
    return ConversationHandler.END


async def start_close_current_cycle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Are you sure you want to close current cycle?", reply_markup=YESNO_KB
    )
    return States.CLOSE_CURRENT_CYCLE_CONFIRM


async def close_current_cycle_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    id = str(update.effective_user.id)
    if update.message.text.lower().startswith("y"):
        _, sessionMaker = init_database(id, Path("/data"))
        with sessionMaker.begin() as session:
            current_cycle = read_current_cycle(session)
            if current_cycle is None:
                await update.message.reply_text("No cycle to close found")
                return ConversationHandler.END
            else:
                current_start_dt = current_cycle.start_dt
        period_stats = get_daily_stats_period(
            id, Path("/data"), current_start_dt, datetime.now()
        )
        total_deficit = period_stats.deficit

        with sessionMaker.begin() as session:
            # Get total deficit
            closed_cycle = close_current_cycle(session)
            start_dt = closed_cycle.start_dt if closed_cycle is not None else None
        if start_dt is not None:
            await update.message.reply_text(
                f"Closed cycle started on {start_dt.strftime('%Y-%m-%d')} "
                f"with deficit {total_deficit} kcal"
            )
    else:
        await update.message.reply_text("Cancelled")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


CYCLE_CREATE_CONV = ConversationHandler(
    entry_points=[CommandHandler("new_cycle", start_create_cycle)],
    states={
        States.START_CREATE_CYCLE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, start_create_cycle)
        ],
        States.CREATE_CYCLE_MAINTENANCE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, create_cycle_maintenance)
        ],
        States.CREATE_CYCLE_CONFIRM: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, create_cycle_confirm)
        ],
        States.CLOSE_CURRENT_CYCLE_CONFIRM: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, close_current_cycle_confirm)
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

FOOD_CREATE_ENTRY_CONV = ConversationHandler(
    entry_points=[CommandHandler("new_food", start_create_food_entry)],
    states={
        States.START_CREATE_FOOD_ENTRY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, start_create_food_entry)
        ],
        States.CREATE_FOOD_ENTRY_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, create_food_entry_name)
        ],
        States.CREATE_FOOD_ENTRY_KCAL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, create_food_entry_kcal)
        ],
        States.CREATE_FOOD_ENTRY_CONFIRM: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, create_food_entry_confirm)
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

EXERCISE_CREATE_ENTRY_CONV = ConversationHandler(
    entry_points=[CommandHandler("new_exercise", start_create_exercise_entry)],
    states={
        States.START_CREATE_EXERCISE_ENTRY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, start_create_exercise_entry)
        ],
        States.CREATE_EXERCISE_ENTRY_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, create_exercise_entry_name)
        ],
        States.CREATE_EXERCISE_ENTRY_KCAL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, create_exercise_entry_kcal)
        ],
        States.CREATE_EXERCISE_ENTRY_CONFIRM: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND, create_exercise_entry_confirm
            )
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

FOOD_DELETE_ENTRY_CONV = ConversationHandler(
    entry_points=[CommandHandler("delete_food", start_delete_food_entry)],
    states={
        States.START_CREATE_FOOD_ENTRY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, start_delete_food_entry)
        ],
        States.DELETE_FOOD_ENTRY_CONFIRM: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, delete_food_entry_confirm)
        ],
        States.DELETE_FOOD_ENTRY_ID: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, delete_food_entry_id)
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

EXERCISE_DELETE_ENTRY_CONV = ConversationHandler(
    entry_points=[CommandHandler("delete_exercise", start_delete_exercise_entry)],
    states={
        States.START_CREATE_EXERCISE_ENTRY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, start_delete_food_entry)
        ],
        States.DELETE_EXERCISE_ENTRY_ID: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, delete_exercise_entry_id)
        ],
        States.DELETE_EXERCISE_ENTRY_CONFIRM: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND, delete_exercise_entry_confirm
            )
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

CYCLE_CLOSE_CURRENT_CONV = ConversationHandler(
    entry_points=[CommandHandler("close_cycle", start_close_current_cycle)],
    states={
        States.CLOSE_CURRENT_CYCLE_CONFIRM: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, close_current_cycle_confirm)
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hi! Welcome to Dietor!")


async def set_commands(app):
    commands = [
        BotCommand("today", "Get today's stats"),
        BotCommand("week", "Get this week's stats"),
        BotCommand("month", "Get this month's stats"),
        BotCommand("week_full", "Get this week's stats with daily breakdown"),
        BotCommand("month_full", "Get this month's stats with daily breakdown"),
        BotCommand("start", "Start the bot"),
        BotCommand("new_cycle", "Start a new cycle"),
        BotCommand("close_cycle", "Close the current cycle"),
        BotCommand("new_food", "Add a food entry"),
        BotCommand("new_exercise", "Add an exercise entry"),
        BotCommand("delete_food", "Delete a food entry"),
        BotCommand("delete_exercise", "Delete an exercise entry"),
        BotCommand("cancel", "Cancel current action"),
    ]
    await app.bot.set_my_commands(commands)


def main():
    app = Application.builder().token("").post_init(set_commands).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", get_day_food_stats))
    app.add_handler(CommandHandler("week", get_week_food_stats))
    app.add_handler(CommandHandler("month", get_month_food_stats))

    get_week_food_stats_full = partial(get_week_food_stats, full=True)
    get_month_food_stats_full = partial(get_month_food_stats, full=True)
    app.add_handler(CommandHandler("week_full", get_week_food_stats_full))
    app.add_handler(CommandHandler("month_full", get_month_food_stats_full))

    app.add_handler(CYCLE_CREATE_CONV)
    app.add_handler(CYCLE_CLOSE_CURRENT_CONV)
    app.add_handler(FOOD_CREATE_ENTRY_CONV)
    app.add_handler(EXERCISE_CREATE_ENTRY_CONV)
    app.add_handler(FOOD_DELETE_ENTRY_CONV)
    app.add_handler(EXERCISE_DELETE_ENTRY_CONV)

    app.run_polling()


if __name__ == "__main__":
    main()
