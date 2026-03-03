import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth import get_current_user_id
from database import get_db
from kafka_client import produce
from models import Match, Message, User
from redis_client import get_redis
from ws_manager import send_to_user

logger = logging.getLogger(__name__)


async def _safe_produce(topic: str, payload: dict):
    try:
        await produce(topic, payload)
    except Exception as exc:
        logger.error("Kafka produce failed: %s", exc)

router = APIRouter(tags=["matches"])


class MatchOut(BaseModel):
    id: str
    other_user_id: str
    other_user_name: str
    other_user_photo: str
    created_at: datetime

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: str
    sender_id: str
    body: str
    created_at: datetime

    class Config:
        from_attributes = True


class SendMessageRequest(BaseModel):
    body: str = Field(..., min_length=1)


@router.get("/matches", response_model=list[MatchOut])
async def list_matches(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Match)
        .options(selectinload(Match.user1), selectinload(Match.user2))
        .where(or_(Match.user1_id == user_id, Match.user2_id == user_id))
        .order_by(Match.created_at.desc())
    )
    matches = result.scalars().all()

    out = []
    for m in matches:
        other = m.user2 if m.user1_id == user_id else m.user1
        out.append(MatchOut(
            id=m.id,
            other_user_id=other.id,
            other_user_name=other.name,
            other_user_photo=other.photo_url,
            created_at=m.created_at,
        ))
    return out


@router.get("/matches/{match_id}/messages", response_model=list[MessageOut])
async def get_messages(
    match_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    match = await _get_match_or_404(match_id, user_id, db)
    result = await db.execute(
        select(Message)
        .where(Message.match_id == match.id)
        .order_by(Message.created_at)
    )
    return result.scalars().all()


@router.post("/matches/{match_id}/messages", response_model=MessageOut, status_code=201)
async def send_message(
    match_id: str,
    req: SendMessageRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    import json
    match = await _get_match_or_404(match_id, user_id, db)

    msg = Message(match_id=match.id, sender_id=user_id, body=req.body)
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    # Determine the other user
    other_id = match.user2_id if match.user1_id == user_id else match.user1_id

    ws_payload = {
        "type": "message",
        "data": {
            "match_id": match_id,
            "message": {
                "id": msg.id,
                "sender_id": user_id,
                "body": req.body,
                "created_at": msg.created_at.isoformat(),
            },
        },
    }

    # Relay via WebSocket (direct connection)
    await send_to_user(other_id, ws_payload)

    # Also publish to Redis pub/sub for multi-instance relay
    await redis.publish("ws_events", json.dumps({"user_id": other_id, "payload": ws_payload}))

    asyncio.create_task(_safe_produce("user_activity", {
        "event": "message_sent",
        "user_id": user_id,
        "match_id": match_id,
        "timestamp": datetime.utcnow().isoformat(),
    }))

    return msg


async def _get_match_or_404(match_id: str, user_id: str, db: AsyncSession) -> Match:
    result = await db.execute(
        select(Match)
        .options(selectinload(Match.user1), selectinload(Match.user2))
        .where(
            Match.id == match_id,
            or_(Match.user1_id == user_id, Match.user2_id == user_id),
        )
    )
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match
