import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Text, DateTime, ForeignKey, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    bio = Column(Text, default="")
    age = Column(Integer, nullable=False)
    photo_url = Column(String(500), default="")
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    swipes_sent = relationship("Swipe", foreign_keys="Swipe.swiper_id", back_populates="swiper")
    swipes_received = relationship("Swipe", foreign_keys="Swipe.target_id", back_populates="target")


class Swipe(Base):
    __tablename__ = "swipes"
    __table_args__ = (UniqueConstraint("swiper_id", "target_id", name="uq_swipe"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    swiper_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    target_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    direction = Column(String(10), nullable=False)  # "like" | "pass"
    created_at = Column(DateTime, default=datetime.utcnow)

    swiper = relationship("User", foreign_keys=[swiper_id], back_populates="swipes_sent")
    target = relationship("User", foreign_keys=[target_id], back_populates="swipes_received")


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("user1_id", "user2_id", name="uq_match"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user1_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    user2_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user1 = relationship("User", foreign_keys=[user1_id])
    user2 = relationship("User", foreign_keys=[user2_id])
    messages = relationship("Message", back_populates="match", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    match_id = Column(UUID(as_uuid=False), ForeignKey("matches.id"), nullable=False, index=True)
    sender_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    match = relationship("Match", back_populates="messages")
    sender = relationship("User")
