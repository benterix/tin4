#!/usr/bin/env python3
"""
Generate AI profile photos for seeded users via ImageRouter API.
Uses black-forest-labs/FLUX-2-max (~$0.07/image) — 20 images ≈ $1.40 total.
Each prompt is tailored to the user's bio/occupation for realism.
Updates photo_url in the database directly.
"""
import asyncio, json, os, sys, urllib.request, urllib.error, time

API_KEY = "29cebbe7eabdf3577ae6dc21a7f54c8c5e47c4c540b70140638b15492d34dc7b"
MODEL = "black-forest-labs/FLUX-2-max"
IR_URL = "https://api.imagerouter.io/v1/openai/images/generations"

# Bio-specific prompts for each user
USERS = [
    {"name": "Alice",  "email": "alice@tin4.demo",
     "prompt": "realistic portrait photo of a 26-year-old woman holding a coffee cup, wearing a light hiking jacket, warm smile, soft natural bokeh background, high quality headshot, 4k photorealistic"},
    {"name": "Bob",    "email": "bob@tin4.demo",
     "prompt": "realistic portrait photo of a 29-year-old man in a modern kitchen apron, casual tech company t-shirt visible underneath, friendly confident expression, soft bokeh background, 4k photorealistic headshot"},
    {"name": "Carol",  "email": "carol@tin4.demo",
     "prompt": "realistic portrait photo of a 24-year-old woman in yoga attire, serene peaceful smile, soft studio lighting with bokeh, hair tied back, 4k photorealistic headshot"},
    {"name": "Dave",   "email": "dave@tin4.demo",
     "prompt": "realistic portrait photo of a 31-year-old man in running gear, athletic build, energetic smile post-run, outdoor background lightly blurred, 4k photorealistic headshot"},
    {"name": "Eve",    "email": "eve@tin4.demo",
     "prompt": "realistic portrait photo of a 27-year-old woman scientist, casual smart attire, small telescope visible in blurred background, intelligent warm expression, soft bokeh, 4k photorealistic headshot"},
    {"name": "Frank",  "email": "frank@tin4.demo",
     "prompt": "realistic portrait photo of a 33-year-old male architect, sharp professional look, architectural blueprints subtly visible in background, confident smile, 4k photorealistic headshot"},
    {"name": "Grace",  "email": "grace@tin4.demo",
     "prompt": "realistic portrait photo of a 25-year-old woman reading a book in a cozy café, warm soft lighting, travel photos on a wall behind her blurred, natural smile, 4k photorealistic headshot"},
    {"name": "Hank",   "email": "hank@tin4.demo",
     "prompt": "realistic portrait photo of a 30-year-old man holding an acoustic guitar, small dog resting near his shoulder, relaxed warm smile, indoor bokeh background, 4k photorealistic headshot"},
    {"name": "Iris",   "email": "iris@tin4.demo",
     "prompt": "realistic portrait photo of a 23-year-old woman marine biologist, casual outdoor wear, ocean or aquarium subtly in blurred background, curious intelligent expression, 4k photorealistic headshot"},
    {"name": "Jack",   "email": "jack@tin4.demo",
     "prompt": "realistic portrait photo of a 28-year-old male startup founder, smart casual blazer over t-shirt, modern office bokeh background, energetic ambitious smile, 4k photorealistic headshot"},
    {"name": "Kara",   "email": "kara@tin4.demo",
     "prompt": "realistic portrait photo of a 26-year-old woman pastry chef, white chef jacket partially visible, warm bright smile, soft kitchen bokeh background, 4k photorealistic headshot"},
    {"name": "Leo",    "email": "leo@tin4.demo",
     "prompt": "realistic portrait photo of a 32-year-old male history teacher, warm cardigan, bookshelves subtly blurred in background, friendly approachable expression, 4k photorealistic headshot"},
    {"name": "Maya",   "email": "maya@tin4.demo",
     "prompt": "realistic portrait photo of a 24-year-old woman UX designer, creative casual style, design sketches subtly visible on desk behind her, bright creative smile, 4k photorealistic headshot"},
    {"name": "Nick",   "email": "nick@tin4.demo",
     "prompt": "realistic portrait photo of a 35-year-old male sailor, sun-weathered tan, casual nautical jacket, sailboat deck blurred in background, confident adventurous expression, 4k photorealistic headshot"},
    {"name": "Olivia", "email": "olivia@tin4.demo",
     "prompt": "realistic portrait photo of a 27-year-old woman nurse, scrubs visible at collar, headphones around neck hinting at DJ hobby, warm caring smile, soft bokeh background, 4k photorealistic headshot"},
    {"name": "Paul",   "email": "paul@tin4.demo",
     "prompt": "realistic portrait photo of a 29-year-old male photographer, camera strap around neck, creative casual style, artistic studio bokeh background, thoughtful creative expression, 4k photorealistic headshot"},
    {"name": "Quinn",  "email": "quinn@tin4.demo",
     "prompt": "realistic portrait photo of a 22-year-old CS student, casual hoodie, laptop subtly visible in blurred campus background, young enthusiastic expression, 4k photorealistic headshot"},
    {"name": "Rachel", "email": "rachel@tin4.demo",
     "prompt": "realistic portrait photo of a 30-year-old female lawyer, sharp professional blazer, confident witty smile hinting at improv comedy side, law office bokeh background, 4k photorealistic headshot"},
    {"name": "Sam",    "email": "sam@tin4.demo",
     "prompt": "realistic portrait photo of a 28-year-old DevOps engineer, casual tech wear, terminal or server rack subtly blurred in background, calm efficient expression, 4k photorealistic headshot"},
    {"name": "Tina",   "email": "tina@tin4.demo",
     "prompt": "realistic portrait photo of a 25-year-old woman ML researcher, smart casual attire, neural network diagram subtly visible on whiteboard behind her, curious analytical expression, 4k photorealistic headshot"},
]


def generate_image(prompt):
    body = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "size": "1024x1024",
        "response_format": "url",
    }).encode()
    req = urllib.request.Request(
        IR_URL, body,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=120)
    data = json.loads(resp.read())
    return data["data"][0]["url"]


async def update_db(email, url):
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from models import User

    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url, echo=False)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await session.execute(
            update(User).where(User.email == email).values(photo_url=url)
        )
        await session.commit()
    await engine.dispose()


async def main():
    sys.path.insert(0, "/app")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://tin4:changeme@postgres:5432/tin4")
    os.environ.setdefault("JWT_SECRET", "x")

    total = len(USERS)
    estimated_cost = total * 0.07
    print(f"Generating {total} profile photos with {MODEL}")
    print(f"Estimated cost: ~${estimated_cost:.2f}\n")

    results = {}
    for i, u in enumerate(USERS, 1):
        print(f"[{i}/{total}] {u['name']}... ", end="", flush=True)
        try:
            url = generate_image(u["prompt"])
            await update_db(u["email"], url)
            results[u["name"]] = url
            print(f"OK → {url[:70]}...")
        except Exception as e:
            print(f"FAILED: {e}")
            results[u["name"]] = None
        time.sleep(0.5)

    ok = sum(1 for v in results.values() if v)
    print(f"\n✅ Generated {ok}/{total} photos successfully")
    print(f"Estimated spend: ~${ok * 0.07:.2f}")
    return results


if __name__ == "__main__":
    asyncio.run(main())
