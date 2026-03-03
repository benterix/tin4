#!/usr/bin/env python3
"""
Smoke test — runs against the live Docker Compose stack.
Usage: python scripts/smoke_test.py
"""
import json
import urllib.request

BASE = "http://localhost:8000"


def post(path, data, headers=None):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode(),
        headers=h,
        method="POST",
    )
    r = urllib.request.urlopen(req)
    return json.loads(r.read())


def get(path, token=None):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, headers=headers)
    r = urllib.request.urlopen(req)
    return json.loads(r.read())


import time
ts = int(time.time())

print("=== TIN4 Smoke Tests ===")

# 1. Register user A
a = post("/api/auth/register", {
    "email": f"smoke_a_{ts}@test.com",
    "name": "Smoke A", "password": "pass123", "age": 28
})
ta = a["access_token"]
uid_a = a["user_id"]
print(f"[1] Register A OK — user_id: {uid_a}")

# 2. Register user B
b = post("/api/auth/register", {
    "email": f"smoke_b_{ts}@test.com",
    "name": "Smoke B", "password": "pass123", "age": 26
})
tb = b["access_token"]
uid_b = b["user_id"]
print(f"[2] Register B OK — user_id: {uid_b}")

# 3. Login
login = post("/api/auth/login", {"email": f"smoke_a_{ts}@test.com", "password": "pass123"})
assert "access_token" in login
print("[3] Login OK")

# 4. Get profiles
profiles = get("/api/profiles?limit=50", token=ta)
assert any(p["id"] == uid_b for p in profiles), "B not in A's profiles"
print(f"[4] Profiles OK — {len(profiles)} results")

# 5. Swipe A → B (like)
sw = post("/api/swipe", {"target_id": uid_b, "direction": "like"}, {"Authorization": "Bearer " + ta})
assert sw["queued"] is True
print(f"[5] Swipe (A→B like) OK — swipe_id: {sw['swipe_id']}")

# 6. Swipe B → A (like) — should create a match via RabbitMQ processor
sw2 = post("/api/swipe", {"target_id": uid_a, "direction": "like"}, {"Authorization": "Bearer " + tb})
assert sw2["queued"] is True
print(f"[6] Swipe (B→A like) OK — match should be processed asynchronously")

# 7. Wait briefly for match processor
import time
time.sleep(2)

# 8. Check matches
matches_a = get("/api/matches", token=ta)
print(f"[7] Matches for A: {len(matches_a)}")
if matches_a:
    print(f"    Match: {matches_a[0]['other_user_name']}")
    mid = matches_a[0]["id"]
    # 9. Send message
    msg = post(f"/api/matches/{mid}/messages", {"body": "Hey! We matched!"}, {"Authorization": "Bearer " + ta})
    assert msg["body"] == "Hey! We matched!"
    print(f"[8] Send message OK — msg_id: {msg['id']}")

    # 10. Get messages
    msgs = get(f"/api/matches/{mid}/messages", token=ta)
    assert len(msgs) >= 1
    print(f"[9] Get messages OK — {len(msgs)} messages")

# 10. GraphQL stats
gql = post("/graphql",
    {"query": "{ stats { totalSwipes likesSent matchesCount matchRate } }"},
    {"Authorization": "Bearer " + ta}
)
stats = gql["data"]["stats"]
assert stats["totalSwipes"] == 1
assert stats["likesSent"] == 1
print(f"[10] GraphQL stats OK — {stats}")

# 11. Health
health = get("/health")
assert health["status"] == "ok"
print("[11] Health OK")

print("\n✅ ALL SMOKE TESTS PASSED")
