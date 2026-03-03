import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user_id
from database import get_db
from kafka_client import produce
from models import Swipe, User
from rabbitmq_client import publish

logger = logging.getLogger(__name__)
router = APIRouter(tags=["swipe"])


async def _safe_publish(queue: str, payload: dict):
    try:
        await publish(queue, payload)
    except Exception as exc:
        logger.error("RabbitMQ publish failed: %s", exc)


async def _safe_produce(topic: str, payload: dict):
    try:
        await produce(topic, payload)
    except Exception as exc:
        logger.error("Kafka produce failed: %s", exc)


class SwipeRequest(BaseModel):
    target_id: str
    direction: str  # "like" | "pass"


@router.post("/swipe", response_model=dict, status_code=202)
async def swipe(
    req: SwipeRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    if req.direction not in ("like", "pass"):
        raise HTTPException(status_code=400, detail="direction must be 'like' or 'pass'")
    if req.target_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot swipe on yourself")

    # verify target exists
    result = await db.execute(select(User).where(User.id == req.target_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Target user not found")

    # check for duplicate swipe
    existing = await db.execute(
        select(Swipe).where(Swipe.swiper_id == user_id, Swipe.target_id == req.target_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already swiped on this user")

    swipe_obj = Swipe(swiper_id=user_id, target_id=req.target_id, direction=req.direction)
    db.add(swipe_obj)
    await db.commit()

    payload = {
        "swipe_id": swipe_obj.id,
        "swiper_id": user_id,
        "target_id": req.target_id,
        "direction": req.direction,
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Publish to RabbitMQ for match processing (fire-and-forget)
    asyncio.create_task(_safe_publish("swipe_events", payload))

    # Publish to Redpanda for analytics (fire-and-forget)
    asyncio.create_task(_safe_produce("swipe_stream", payload))

    return {"queued": True, "swipe_id": swipe_obj.id}
