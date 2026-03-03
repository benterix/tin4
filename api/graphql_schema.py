"""
Strawberry GraphQL schema.

Queries:
  - profiles(limit) → [Profile]
  - myMatches → [MatchInfo]
  - stats → Stats
"""
from typing import List, Optional

import strawberry
from fastapi import Request
from sqlalchemy import func, select, or_, not_, and_
from sqlalchemy.orm import selectinload
from strawberry.fastapi import GraphQLRouter
from strawberry.types import Info

from database import AsyncSessionLocal
from models import Match, Swipe, User
from redis_client import get_redis


# ── Types ─────────────────────────────────────────────────────────────────

@strawberry.type
class Profile:
    id: str
    name: str
    bio: str
    age: int
    photo_url: str
    is_online: bool = False


@strawberry.type
class MatchInfo:
    id: str
    other_user_id: str
    other_user_name: str
    other_user_photo: str


@strawberry.type
class Stats:
    total_swipes: int
    likes_sent: int
    passes_sent: int
    matches_count: int
    match_rate: float


# ── Context helper ────────────────────────────────────────────────────────

def _get_user_id(info: Info) -> Optional[str]:
    request = info.context.get("request") if isinstance(info.context, dict) else getattr(info.context, "request", None)
    if request is None:
        return None
    return getattr(request.state, "user_id", None)


# ── Queries ───────────────────────────────────────────────────────────────

@strawberry.type
class Query:
    @strawberry.field
    async def profiles(self, info: Info, limit: int = 10) -> List[Profile]:
        user_id = _get_user_id(info)
        if not user_id:
            return []

        async with AsyncSessionLocal() as db:
            redis = await get_redis()
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
            profiles = []
            for u in users:
                online = await redis.exists(f"presence:{u.id}") == 1
                profiles.append(Profile(
                    id=u.id,
                    name=u.name,
                    bio=u.bio,
                    age=u.age,
                    photo_url=u.photo_url,
                    is_online=online,
                ))
            return profiles

    @strawberry.field
    async def my_matches(self, info: Info) -> List[MatchInfo]:
        user_id = _get_user_id(info)
        if not user_id:
            return []

        async with AsyncSessionLocal() as db:
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
                out.append(MatchInfo(
                    id=m.id,
                    other_user_id=other.id,
                    other_user_name=other.name,
                    other_user_photo=other.photo_url,
                ))
            return out

    @strawberry.field
    async def stats(self, info: Info) -> Stats:
        user_id = _get_user_id(info)
        if not user_id:
            return Stats(
                total_swipes=0, likes_sent=0, passes_sent=0,
                matches_count=0, match_rate=0.0,
            )

        async with AsyncSessionLocal() as db:
            total_result = await db.execute(
                select(func.count()).where(Swipe.swiper_id == user_id)
            )
            total = total_result.scalar() or 0

            likes_result = await db.execute(
                select(func.count()).where(
                    Swipe.swiper_id == user_id, Swipe.direction == "like"
                )
            )
            likes = likes_result.scalar() or 0

            matches_result = await db.execute(
                select(func.count()).where(
                    or_(Match.user1_id == user_id, Match.user2_id == user_id)
                )
            )
            matches_count = matches_result.scalar() or 0

            match_rate = (matches_count / likes * 100) if likes > 0 else 0.0

            return Stats(
                total_swipes=total,
                likes_sent=likes,
                passes_sent=total - likes,
                matches_count=matches_count,
                match_rate=round(match_rate, 1),
            )


schema = strawberry.Schema(query=Query)


def get_graphql_router(app_state) -> GraphQLRouter:
    async def get_context(request: Request) -> dict:
        return {"request": request}

    return GraphQLRouter(schema, context_getter=get_context)
