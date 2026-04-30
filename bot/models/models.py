import enum
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Category(str, enum.Enum):
    LOST = "LOST"
    INJURED = "INJURED"
    STERILIZATION = "STERILIZATION"
    AGGRESSIVE = "AGGRESSIVE"
    DEAD = "DEAD"


class Status(str, enum.Enum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_FEEDBACK = "AWAITING_FEEDBACK"  # погоджено, чекаємо фідбек від користувача
    DONE = "DONE"
    REJECTED = "REJECTED"


class MediaType(str, enum.Enum):
    PHOTO = "photo"
    VIDEO = "video"


ALLOWED_TRANSITIONS: dict[Status, set[Status]] = {
    Status.NEW: {Status.IN_PROGRESS, Status.REJECTED},
    Status.IN_PROGRESS: {Status.AWAITING_FEEDBACK, Status.DONE, Status.REJECTED},
    Status.AWAITING_FEEDBACK: {Status.DONE, Status.REJECTED},
    Status.DONE: set(),
    Status.REJECTED: set(),
}


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    requests = relationship("Request", back_populates="user")
    bite_reports = relationship("BiteReport", back_populates="user")


class Request(Base):
    __tablename__ = "requests"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category = Column(Enum(Category), nullable=False)
    description = Column(String, nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    address_text = Column(String, nullable=True)
    contact = Column(String, nullable=True)
    status = Column(Enum(Status), default=Status.NEW)
    admin_comment = Column(String, nullable=True)
    feedback_text = Column(String, nullable=True)   # фідбек користувача після стерилізації
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="requests")
    media = relationship("Media", back_populates="request", cascade="all, delete-orphan")


class Media(Base):
    __tablename__ = "media"

    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("requests.id"), nullable=False)
    file_id = Column(String, nullable=False)
    type = Column(Enum(MediaType), nullable=False)

    request = relationship("Request", back_populates="media")


async def create_tables(engine: AsyncEngine) -> None:
    """Create all database tables using the provided async engine."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class BiteReport(Base):
    """Звіт про укус агресивної тварини."""
    __tablename__ = "bite_reports"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    bite_date = Column(String, nullable=True)        # дата укусу
    location = Column(String, nullable=True)         # місце укусу
    animal_description = Column(String, nullable=True)  # опис тварини
    contact = Column(String, nullable=True)          # контакт людини
    vaccinated = Column(String, nullable=True)       # чи щеплена тварина
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="bite_reports")
