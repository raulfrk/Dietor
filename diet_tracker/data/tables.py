from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    create_engine,
    event,
    literal,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)


class Base(DeclarativeBase):
    pass


class EntryNotFound(Exception):
    pass


class Cycle(Base):
    __tablename__ = "cycle"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    maintenance_kcal: Mapped[int] = mapped_column(Integer, nullable=False, default=2000)
    daily_deficit_goal: Mapped[int] = mapped_column(
        Integer, nullable=False, default=500
    )

    food_entries: Mapped[list["FoodEntry"]] = relationship(
        back_populates="cycle",
        cascade="all, delete-orphan",
        passive_deletes=True,
        single_parent=True,
        order_by="FoodEntry.dt",
    )

    exercise_entries: Mapped[list["ExerciseEntry"]] = relationship(
        back_populates="cycle",
        cascade="all, delete-orphan",
        passive_deletes=True,
        single_parent=True,
        order_by="ExerciseEntry.dt",
    )

    __table_args__ = (
        # allow only one row where end_dt IS NULL
        Index(
            "uq_cycle_one_open",
            literal(1),
            unique=True,
            sqlite_where=(end_dt.is_(None)),
        ),
        CheckConstraint(
            "maintenance_kcal > 0", name="ck_cycle_maintenance_kcal_positive"
        ),
    )

    class InvalidOpenCloseCycles(Exception):
        pass

    class CannotCreate(Exception):
        pass

    class NoOpenCycle(Exception):
        pass


class FoodEntry(Base):
    __tablename__ = "food"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kcal: Mapped[int] = mapped_column(Integer, nullable=False)
    dt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    cycle_id: Mapped[int] = mapped_column(
        ForeignKey("cycle.id", ondelete="CASCADE"), nullable=False, index=True
    )

    cycle: Mapped[Cycle] = relationship(back_populates="food_entries")

    __table_args__ = (CheckConstraint("kcal >= 0", name="ck_food_kcal_nonneg"),)


class ExerciseEntry(Base):
    __tablename__ = "exercise"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kcal: Mapped[int] = mapped_column(Integer, nullable=False)
    dt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    cycle_id: Mapped[int] = mapped_column(
        ForeignKey("cycle.id", ondelete="CASCADE"), nullable=False, index=True
    )

    cycle: Mapped[Cycle] = relationship(back_populates="exercise_entries")

    __table_args__ = (CheckConstraint("kcal >= 0", name="ck_exercise_kcal_nonneg"),)


def init_database(user_id: str, path: Path):
    """Initialize database for given user."""

    engine = create_engine(f"sqlite:///{path/user_id}.sqlite", echo=False)

    # Enable DB-level FK enforcement for EVERY connection
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=True)

    return engine, SessionLocal
