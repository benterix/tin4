from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, and_, not_, exists
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user_id
from database import get_db
from models import User, Swipe
from redis_client import get_redis

router = APIRouter(tags=["profiles"])


class ProfileOut(BaseModel):
    id: str
    name: str
    bio: str
    age: int
    photo_url: str
    is_online: bool = False

    class Config:
        from_attributes = True


@router.get("/profiles", response_model=list[ProfileOut])
async def get_profiles(
    limit: int = 10,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Return users that the current user hasn't swiped on yet."""
    already_swiped = select(Swipe.target_id).where(Swipe.swiper_id == user_id)

    result = await db.execute(
        select(User)
        .where(
            and_(
                User.id != user_id,
                not_(User.id.in_(already_swiped)),
            )
        )
        .limit(limit)
    )
    users = result.scalars().all()

    # enrich with presence from Redis
    profiles = []
    for u in users:
        online = await redis.exists(f"presence:{u.id}") == 1
        profiles.append(ProfileOut(
            id=u.id,
            name=u.name,
            bio=u.bio,
            age=u.age,
            photo_url=u.photo_url,
            is_online=online,
        ))
    return profiles
