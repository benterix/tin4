#!/usr/bin/env python3
"""
Generate AI profile photos for seeded users via ImageRouter API.
Uses asiryan/Realistic-Vision (~$0.002/image) — 20 images ≈ $0.04 total.
Updates photo_url in the database directly.
"""
import asyncio, json, os, sys, urllib.request, urllib.error, time

API_KEY = "29cebbe7eabdf3577ae6dc21a7f54c8c5e47c4c540b70140638b15492d34dc7b"
MODEL = "asiryan/Realistic-Vision"
IR_URL = "https://api.imagerouter.io/v1/openai/images/generations"

# User data matching seed.py
USERS = [
    {"name": "Alice",  "age": 26, "bio": "Coffee addict & hiker",         "gender": "woman"},
    {"name": "Bob",    "age": 29, "bio": "Software engineer, chef",        "gender": "man"},
    {"name": "Carol",  "age": 24, "bio": "Yoga instructor, loves jazz",    "gender": "woman"},
    {"name": "Dave",   "age": 31, "bio": "Marathon runner",               "gender": "man"},
    {"name": "Eve",    "age": 27, "bio": "Data scientist, astronomer",     "gender": "woman"},
    {"name": "Frank",  "age": 33, "bio": "Architect",                     "gender": "man"},
    {"name": "Grace",  "age": 25, "bio": "Bookworm, travel enthusiast",    "gender": "woman"},
    {"name": "Hank",   "age": 30, "bio": "Guitarist, dog dad",            "gender": "man"},
    {"name": "Iris",   "age": 23, "bio": "Marine biologist",              "gender": "woman"},
    {"name": "Jack",   "age": 28, "bio": "Startup founder",               "gender": "man"},
    {"name": "Kara",   "age": 26, "bio": "Pastry chef, cyclist",          "gender": "woman"},
    {"name": "Leo",    "age": 32, "bio": "History teacher",               "gender": "man"},
    {"name": "Maya",   "age": 24, "bio": "UX designer",                   "gender": "woman"},
    {"name": "Nick",   "age": 35, "bio": "Sailor",                        "gender": "man"},
    {"name": "Olivia", "age": 27, "bio": "Nurse, weekend DJ",             "gender": "woman"},
    {"name": "Paul",   "age": 29, "bio": "Photographer",                  "gender": "man"},
    {"name": "Quinn",  "age": 22, "bio": "CS student",                    "gender": "person"},
    {"name": "Rachel", "age": 30, "bio": "Lawyer, improv comedian",       "gender": "woman"},
    {"name": "Sam",    "age": 28, "bio": "DevOps engineer",               "gender": "man"},
    {"name": "Tina",   "age": 25, "bio": "ML researcher",                 "gender": "woman"},
]

STYLE_HINTS = {
    "woman": "young professional woman, diverse ethnicities, natural makeup, warm smile",
    "man":   "young professional man, diverse ethnicities, friendly expression",
    "person":"young professional person, friendly expression",
}

def make_prompt(u):
    style = STYLE_HINTS[u["gender"]]
    return (
        f"realistic portrait photo of a {u['age']}-year-old {style}, "
        f"bokeh background, soft natural lighting, high quality headshot, "
        f"casual professional attire, 4k, photorealistic"
    )

def generate_image(prompt):
    body = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "size": "512x512",
        "response_format": "url",
    }).encode()
    req = urllib.request.Request(
        IR_URL, body,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=60)
    data = json.loads(resp.read())
    return data["data"][0]["url"]


async def update_db(name, url):
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://tin4:changeme@localhost:5432/tin4")
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from models import User

    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url, echo=False)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        email = f"{name.lower()}@tin4.demo"
        await session.execute(
            update(User).where(User.email == email).values(photo_url=url)
        )
        await session.commit()
    await engine.dispose()


async def main():
    # Run inside api container — sys.path already has /app
    sys.path.insert(0, "/app")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://tin4:changeme@postgres:5432/tin4")
    os.environ.setdefault("JWT_SECRET", "x")

    print(f"Generating {len(USERS)} profile photos with {MODEL}")
    print(f"Estimated cost: ~${len(USERS) * 0.002:.3f}\n")

    results = {}
    total = len(USERS)
    for i, u in enumerate(USERS, 1):
        prompt = make_prompt(u)
        print(f"[{i}/{total}] {u['name']} ({u['age']})... ", end="", flush=True)
        try:
            url = generate_image(prompt)
            await update_db(u["name"], url)
            results[u["name"]] = url
            print(f"OK → {url[:60]}...")
        except Exception as e:
            print(f"FAILED: {e}")
            results[u["name"]] = None
        time.sleep(0.5)  # be polite

    ok = sum(1 for v in results.values() if v)
    print(f"\n✅ Generated {ok}/{total} photos successfully")
    return results


if __name__ == "__main__":
    asyncio.run(main())
