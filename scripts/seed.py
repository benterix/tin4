#!/usr/bin/env python3
"""
Seed script — populates the TIN4 database with 20 fake user profiles.

Usage (inside the running api container or with DATABASE_URL set):
    python scripts/seed.py

Or via Docker Compose:
    docker compose exec api python /app/../scripts/seed.py
    (better: copy to api/ and run from there)
"""
import asyncio
import os
import sys

# Allow running from project root or scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://tin4:changeme@localhost:5432/tin4")
os.environ.setdefault("JWT_SECRET", "supersecretkey_change_in_production")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from models import Base, User
from auth import hash_password

USERS = [
    {"name": "Alice",    "email": "alice@tin4.demo",    "age": 26, "bio": "Coffee addict & hiker ☕🏔️"},
    {"name": "Bob",      "email": "bob@tin4.demo",      "age": 29, "bio": "Software engineer by day, chef by night"},
    {"name": "Carol",    "email": "carol@tin4.demo",    "age": 24, "bio": "Yoga instructor who loves jazz 🎷"},
    {"name": "Dave",     "email": "dave@tin4.demo",     "age": 31, "bio": "Marathon runner. 42km is just a warm-up."},
    {"name": "Eve",      "email": "eve@tin4.demo",      "age": 27, "bio": "Data scientist & amateur astronomer 🌌"},
    {"name": "Frank",    "email": "frank@tin4.demo",    "age": 33, "bio": "Architect. I design buildings AND databases."},
    {"name": "Grace",    "email": "grace@tin4.demo",    "age": 25, "bio": "Bookworm 📚 | Travel enthusiast ✈️"},
    {"name": "Hank",     "email": "hank@tin4.demo",     "age": 30, "bio": "Guitarist in a band. Dog dad 🐶"},
    {"name": "Iris",     "email": "iris@tin4.demo",     "age": 23, "bio": "Marine biologist who talks to fish 🐠"},
    {"name": "Jack",     "email": "jack@tin4.demo",     "age": 28, "bio": "Startup founder. 3 exits. 0 hobbies."},
    {"name": "Kara",     "email": "kara@tin4.demo",     "age": 26, "bio": "Pastry chef 🥐 | Cycling on weekends"},
    {"name": "Leo",      "email": "leo@tin4.demo",      "age": 32, "bio": "History teacher who quotes Marcus Aurelius"},
    {"name": "Maya",     "email": "maya@tin4.demo",     "age": 24, "bio": "UX designer. I hate bad kerning with passion."},
    {"name": "Nick",     "email": "nick@tin4.demo",     "age": 35, "bio": "Sailor & occasional storm chaser ⛵"},
    {"name": "Olivia",   "email": "olivia@tin4.demo",   "age": 27, "bio": "Nurse + weekend DJ 🎧"},
    {"name": "Paul",     "email": "paul@tin4.demo",     "age": 29, "bio": "Photographer. The world is my darkroom."},
    {"name": "Quinn",    "email": "quinn@tin4.demo",    "age": 22, "bio": "CS student building cool side projects"},
    {"name": "Rachel",   "email": "rachel@tin4.demo",   "age": 30, "bio": "Lawyer who does improv comedy on Fridays"},
    {"name": "Sam",      "email": "sam@tin4.demo",      "age": 28, "bio": "DevOps engineer. I containerize everything."},
    {"name": "Tina",     "email": "tina@tin4.demo",     "age": 25, "bio": "Biologist turned ML researcher 🧬🤖"},
]

PASSWORD = "demo1234"


async def seed():
    database_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://tin4:changeme@localhost:5432/tin4")
    print(f"Connecting to: {database_url}")

    engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    seeded = 0
    async with session_factory() as db:
        for i, u in enumerate(USERS):
            # Check if already exists
            result = await db.execute(select(User).where(User.email == u["email"]))
            if result.scalar_one_or_none():
                print(f"  skip {u['email']} (already exists)")
                continue

            photo_url = f"https://i.pravatar.cc/300?img={i + 1}"
            user = User(
                email=u["email"],
                name=u["name"],
                bio=u["bio"],
                age=u["age"],
                photo_url=photo_url,
                password_hash=hash_password(PASSWORD),
            )
            db.add(user)
            seeded += 1
            print(f"  + {u['name']} ({u['email']})")

        await db.commit()

    await engine.dispose()
    print(f"\nDone. Seeded {seeded} users (password for all: '{PASSWORD}')")


if __name__ == "__main__":
    asyncio.run(seed())
