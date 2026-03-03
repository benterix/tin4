import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import (
    create_access_token, get_current_user_id, hash_password, verify_password,
)
from database import get_db
from kafka_client import produce
from models import User

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


async def _safe_produce(topic: str, payload: dict):
    try:
        await produce(topic, payload)
    except Exception as exc:
        logger.error("Kafka produce failed: %s", exc)


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    age: int
    bio: str = ""
    photo_url: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    bio: str
    age: int
    photo_url: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/register", response_model=dict, status_code=201)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == req.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=req.email,
        name=req.name,
        bio=req.bio,
        age=req.age,
        photo_url=req.photo_url or f"https://i.pravatar.cc/300?u={req.email}",
        password_hash=hash_password(req.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    asyncio.create_task(_safe_produce("user_activity", {
        "event": "register",
        "user_id": user.id,
        "timestamp": datetime.utcnow().isoformat(),
    }))
    return {"access_token": token, "token_type": "bearer", "user_id": user.id}


@router.post("/login", response_model=dict)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user.id)
    asyncio.create_task(_safe_produce("user_activity", {
        "event": "login",
        "user_id": user.id,
        "timestamp": datetime.utcnow().isoformat(),
    }))
    return {"access_token": token, "token_type": "bearer", "user_id": user.id}


@router.get("/me", response_model=UserOut)
async def me(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
