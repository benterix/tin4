"""
Match Processor
===============
Consumes swipe events from RabbitMQ queue `swipe_events`.
When a mutual "like" is detected, creates a Match row in the database,
publishes a match notification to:
  - RabbitMQ queue `match_notifications` (picked up by WebSocket relay)
  - Redis pub/sub channel `ws_events` (direct relay to API WebSocket manager)
  - Redpanda topic `match_events` (for analytics)
"""
import asyncio
import json
import logging
import os
import signal
from datetime import datetime

import aio_pika
import redis.asyncio as aioredis
from aiokafka import AIOKafkaProducer
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MATCH] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://tin4:changeme@postgres:5432/tin4")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
REDPANDA_BROKERS = os.getenv("REDPANDA_BROKERS", "redpanda:9092")

# ── ORM (minimal, shares same models as API) ───────────────────────────────
Base = declarative_base()

import uuid
from sqlalchemy import Column, String, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID


def _uuid():
    return str(uuid.uuid4())


class Swipe(Base):
    __tablename__ = "swipes"
    __table_args__ = (UniqueConstraint("swiper_id", "target_id"),)
    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    swiper_id = Column(UUID(as_uuid=False), nullable=False)
    target_id = Column(UUID(as_uuid=False), nullable=False)
    direction = Column(String(10), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("user1_id", "user2_id"),)
    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user1_id = Column(UUID(as_uuid=False), nullable=False)
    user2_id = Column(UUID(as_uuid=False), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name = Column(String(100))
    photo_url = Column(String(500))


# ── DB setup ───────────────────────────────────────────────────────────────

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

_redis: aioredis.Redis | None = None
_producer: AIOKafkaProducer | None = None


async def get_redis():
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


async def get_producer():
    global _producer
    if _producer is None:
        for attempt in range(15):
            try:
                _producer = AIOKafkaProducer(
                    bootstrap_servers=REDPANDA_BROKERS,
                    value_serializer=lambda v: json.dumps(v).encode(),
                )
                await _producer.start()
                logger.info("Kafka producer started")
                break
            except Exception as exc:
                logger.warning("Kafka connect %d: %s", attempt + 1, exc)
                _producer = None
                await asyncio.sleep(3)
    return _producer


async def process_swipe(payload: dict, db: AsyncSession):
    swiper_id = payload["swiper_id"]
    target_id = payload["target_id"]
    direction = payload["direction"]

    if direction != "like":
        return  # Only "like" swipes can create matches

    # Check if target already liked swiper
    result = await db.execute(
        select(Swipe).where(
            Swipe.swiper_id == target_id,
            Swipe.target_id == swiper_id,
            Swipe.direction == "like",
        )
    )
    reverse_like = result.scalar_one_or_none()
    if not reverse_like:
        return  # No mutual like yet

    # Prevent duplicate matches (check both orientations)
    existing = await db.execute(
        select(Match).where(
            or_(
                (Match.user1_id == swiper_id) & (Match.user2_id == target_id),
                (Match.user1_id == target_id) & (Match.user2_id == swiper_id),
            )
        )
    )
    if existing.scalar_one_or_none():
        logger.info("Match already exists for %s <-> %s", swiper_id, target_id)
        return

    # Create match
    match = Match(user1_id=swiper_id, user2_id=target_id)
    db.add(match)
    await db.commit()
    await db.refresh(match)
    logger.info("🎉 Match created: %s <-> %s (match_id=%s)", swiper_id, target_id, match.id)

    # Fetch user names for the notification
    u1_result = await db.execute(select(User).where(User.id == swiper_id))
    u2_result = await db.execute(select(User).where(User.id == target_id))
    u1 = u1_result.scalar_one_or_none()
    u2 = u2_result.scalar_one_or_none()

    redis = await get_redis()
    producer = await get_producer()

    for user_id, other in [(swiper_id, u2), (target_id, u1)]:
        ws_payload = {
            "type": "match",
            "data": {
                "match_id": match.id,
                "other_user": {
                    "id": other.id if other else "",
                    "name": other.name if other else "Someone",
                    "photo_url": other.photo_url if other else "",
                },
                "created_at": match.created_at.isoformat(),
            },
        }
        # Publish to Redis pub/sub → relayed by API's WS manager
        await redis.publish("ws_events", json.dumps({"user_id": user_id, "payload": ws_payload}))
        logger.info("Published match notification to Redis for user %s", user_id)

    # Publish to Redpanda
    if producer:
        await producer.send_and_wait("match_events", {
            "event": "match",
            "match_id": match.id,
            "user1_id": swiper_id,
            "user2_id": target_id,
            "timestamp": datetime.utcnow().isoformat(),
        })


async def main():
    logger.info("Match processor starting…")

    # Wait for RabbitMQ
    connection: aio_pika.RobustConnection | None = None
    for attempt in range(20):
        try:
            connection = await aio_pika.connect_robust(RABBITMQ_URL)
            break
        except Exception as exc:
            logger.warning("RabbitMQ connect %d: %s", attempt + 1, exc)
            await asyncio.sleep(3)
    else:
        logger.error("Cannot connect to RabbitMQ — exiting")
        return

    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)
    queue = await channel.declare_queue("swipe_events", durable=True)

    logger.info("Listening on queue 'swipe_events' …")

    async def on_message(message: aio_pika.IncomingMessage):
        async with message.process():
            try:
                payload = json.loads(message.body.decode())
                async with SessionLocal() as db:
                    await process_swipe(payload, db)
            except Exception as exc:
                logger.error("Error processing swipe: %s", exc)

    await queue.consume(on_message)

    stop = asyncio.get_running_loop().create_future()

    def _shutdown():
        if not stop.done():
            stop.set_result(None)

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, _shutdown)
    loop.add_signal_handler(signal.SIGINT, _shutdown)

    await stop

    logger.info("Shutting down match processor")
    if _producer:
        await _producer.stop()
    await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
