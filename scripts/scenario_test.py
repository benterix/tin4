#!/usr/bin/env python3
"""
Comprehensive user scenario test against the live stack.
Tests real user flows: register, browse, swipe, match, chat, logout.
Run: python3 scripts/scenario_test.py [--base https://37.27.16.14.nip.io]
"""
import json, time, sys, urllib.request, urllib.error, ssl

BASE = sys.argv[2] if len(sys.argv) > 2 else (
    sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else
    "https://37.27.16.14.nip.io"
)
# Accept self-signed certs for local testing
ctx = ssl.create_default_context()
if "localhost" in BASE or "127.0.0.1" in BASE:
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
errors = []

def req(method, path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(BASE + path, body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r, context=ctx)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def check(label, condition, detail=""):
    if condition:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}" + (f" — {detail}" if detail else ""))
        errors.append(label)

ts = int(time.time())
print(f"\n{'='*55}")
print(f"  TIN4 Scenario Tests  →  {BASE}")
print(f"{'='*55}\n")


# ── 1. Health check ──────────────────────────────────────────────────────
print("1. Health check")
status, body = req("GET", "/health")
check("GET /health returns 200", status == 200)
check("status is ok", body.get("status") == "ok", body)


# ── 2. Register User A ───────────────────────────────────────────────────
print("\n2. Register User A")
status, body = req("POST", "/api/auth/register", {
    "email": f"scenario_a_{ts}@tin4example.com",
    "name": "Alice Scenario", "password": "pass1234", "age": 27, "bio": "Loves hiking"
})
check("201 Created", status == 201)
check("access_token present", "access_token" in body)
token_a = body.get("access_token", "")
uid_a = body.get("user_id", "")


# ── 3. Register User B ───────────────────────────────────────────────────
print("\n3. Register User B")
status, body = req("POST", "/api/auth/register", {
    "email": f"scenario_b_{ts}@tin4example.com",
    "name": "Bob Scenario", "password": "pass1234", "age": 29, "bio": "Into coffee"
})
check("201 Created", status == 201)
token_b = body.get("access_token", "")
uid_b = body.get("user_id", "")


# ── 4. Register User C (no match) ────────────────────────────────────────
print("\n4. Register User C")
status, body = req("POST", "/api/auth/register", {
    "email": f"scenario_c_{ts}@tin4example.com",
    "name": "Carol Scenario", "password": "pass1234", "age": 25
})
check("201 Created", status == 201)
token_c = body.get("access_token", "")
uid_c = body.get("user_id", "")


# ── 5. Login ─────────────────────────────────────────────────────────────
print("\n5. Login (User A)")
status, body = req("POST", "/api/auth/login", {
    "email": f"scenario_a_{ts}@tin4example.com", "password": "pass1234"
})
check("200 OK", status == 200)
check("token returned", "access_token" in body)
token_a = body.get("access_token", token_a)

status, _ = req("POST", "/api/auth/login", {"email": f"scenario_a_{ts}@tin4example.com", "password": "wrong"})
check("401 on wrong password", status == 401)

status, _ = req("POST", "/api/auth/login", {"email": "nobody@tin4example.com", "password": "x"})
check("401 on unknown email", status == 401)


# ── 6. /me endpoint ──────────────────────────────────────────────────────
print("\n6. /me — authenticated user info")
status, body = req("GET", "/api/auth/me", token=token_a)
check("200 OK", status == 200)
check("returns correct name", body.get("name") == "Alice Scenario", body.get("name"))
check("no password_hash exposed", "password_hash" not in body)

status, body = req("GET", "/api/auth/me")
check("401 without token", status == 401)


# ── 7. Browse profiles ───────────────────────────────────────────────────
print("\n7. Browse profiles")
status, body = req("GET", "/api/profiles?limit=50", token=token_a)
check("200 OK", status == 200)
check("list returned", isinstance(body, list))
check("B is visible to A", any(p["id"] == uid_b for p in body), "B not in A's feed")
check("C is visible to A", any(p["id"] == uid_c for p in body))
check("A not in own feed", not any(p["id"] == uid_a for p in body))

status, _ = req("GET", "/api/profiles")
check("401 without token", status == 401)


# ── 8. Swipe — invalid cases ─────────────────────────────────────────────
print("\n8. Swipe validation")
status, body = req("POST", "/api/swipe", {"target_id": uid_b, "direction": "love"}, token=token_a)
check("400 on invalid direction", status == 400)

status, body = req("POST", "/api/swipe", {"target_id": uid_a, "direction": "like"}, token=token_a)
check("400 on self-swipe", status == 400)

status, body = req("POST", "/api/swipe", {"target_id": "00000000-0000-0000-0000-000000000000", "direction": "like"}, token=token_a)
check("404 on nonexistent user", status == 404)


# ── 9. A passes on C ────────────────────────────────────────────────────
print("\n9. A passes on C (one-sided pass)")
status, body = req("POST", "/api/swipe", {"target_id": uid_c, "direction": "pass"}, token=token_a)
check("202 Accepted", status == 202, body)
check("queued=True", body.get("queued") is True)

status, _ = req("POST", "/api/swipe", {"target_id": uid_c, "direction": "pass"}, token=token_a)
check("409 on duplicate swipe", status == 409)


# ── 10. A likes B ────────────────────────────────────────────────────────
print("\n10. A likes B (mutual like scenario)")
status, body = req("POST", "/api/swipe", {"target_id": uid_b, "direction": "like"}, token=token_a)
check("202 Accepted (A→B like)", status == 202, body)

# No match yet — B hasn't liked A
time.sleep(1)
status, matches = req("GET", "/api/matches", token=token_a)
check("0 matches before mutual like", status == 200 and len(matches) == 0, f"got {len(matches)}")


# ── 11. B likes A — creates match ────────────────────────────────────────
print("\n11. B likes A — mutual match")
status, body = req("POST", "/api/swipe", {"target_id": uid_a, "direction": "like"}, token=token_b)
check("202 Accepted (B→A like)", status == 202, body)

time.sleep(3)  # wait for match-processor
status, matches_a = req("GET", "/api/matches", token=token_a)
check("A has 1 match", status == 200 and len(matches_a) == 1, f"got {len(matches_a)}")

if matches_a:
    m = matches_a[0]
    check("other_user is Bob", m["other_user_name"] == "Bob Scenario", m.get("other_user_name"))
    mid = m["id"]

    status, matches_b = req("GET", "/api/matches", token=token_b)
    check("B also sees match", len(matches_b) == 1)

    # B can't match with someone who already matched
    status, _ = req("POST", "/api/swipe", {"target_id": uid_a, "direction": "like"}, token=token_b)
    check("409 on duplicate swipe", status == 409)


# ── 12. Messages ─────────────────────────────────────────────────────────
print("\n12. Messaging in match")
if matches_a:
    status, msg = req("POST", f"/api/matches/{mid}/messages", {"body": "Hey Bob!"}, token=token_a)
    check("201 message sent", status == 201)
    check("body correct", msg.get("body") == "Hey Bob!")
    check("sender is A", msg.get("sender_id") == uid_a)

    status, msg2 = req("POST", f"/api/matches/{mid}/messages", {"body": "Alice! Great to meet you"}, token=token_b)
    check("B can reply", status == 201)

    status, msgs = req("GET", f"/api/matches/{mid}/messages", token=token_a)
    check("GET messages returns list", status == 200 and isinstance(msgs, list))
    check("2 messages in thread", len(msgs) == 2, f"got {len(msgs)}")
    check("ordered chronologically", msgs[0]["body"] == "Hey Bob!")

    # A can't message in a match they're not in
    status, _ = req("GET", f"/api/matches/{mid}/messages", token=token_c)
    check("C can't read A-B chat", status == 404)

    # Empty message
    status, _ = req("POST", f"/api/matches/{mid}/messages", {"body": ""}, token=token_a)
    check("empty body rejected (422)", status == 422)


# ── 13. GraphQL ──────────────────────────────────────────────────────────
print("\n13. GraphQL")
status, body = req("POST", "/graphql", {"query": "{ stats { totalSwipes likesSent matchesCount matchRate } }"}, token=token_a)
check("stats query 200", status == 200, body)
if status == 200:
    s = body.get("data", {}).get("stats", {})
    check("totalSwipes=2 (B-like + C-pass)", s.get("totalSwipes") == 2, s)
    check("likesSent=1", s.get("likesSent") == 1, s)
    check("matchesCount=1", s.get("matchesCount") == 1, s)
    check("matchRate=100% (1 like → 1 match)", s.get("matchRate") == 100.0, s)

status, body = req("POST", "/graphql", {"query": "{ profiles(limit: 3) { id name age } }"}, token=token_a)
check("profiles query 200", status == 200)
if status == 200:
    profiles = body.get("data", {}).get("profiles", [])
    check("profiles list returned", len(profiles) > 0, f"got {len(profiles)}")

status, _ = req("POST", "/graphql", {"query": "{ stats { totalSwipes } }"})
check("GQL unauthenticated → empty stats", status == 200)  # returns 0s, not 401


# ── 14. Logout simulation (token invalidation is stateless JWT) ──────────
print("\n14. JWT is stateless (logout = discard token client-side)")
status, _ = req("GET", "/api/auth/me", token=token_a)
check("valid token works", status == 200)
status, _ = req("GET", "/api/auth/me", token="invalid.jwt.token")
check("tampered token rejected", status == 401)


# ── 15. C likes B — no match (B hasn't liked C) ──────────────────────────
print("\n15. One-sided like — no match")
status, _ = req("POST", "/api/swipe", {"target_id": uid_b, "direction": "like"}, token=token_c)
check("202 Accepted (C→B like)", status == 202)
time.sleep(2)
status, matches_c = req("GET", "/api/matches", token=token_c)
check("C has no matches yet", len(matches_c) == 0, f"got {len(matches_c)}")


# ── 16. Profile feed excludes already-swiped users ───────────────────────
print("\n16. Profile feed excludes already-swiped users")
status, feed = req("GET", "/api/profiles?limit=100", token=token_a)
check("200 OK", status == 200)
check("B not in A's feed (swiped)", not any(p["id"] == uid_b for p in feed))
check("C not in A's feed (swiped)", not any(p["id"] == uid_c for p in feed))


# ── Summary ───────────────────────────────────────────────────────────────
print(f"\n{'='*55}")
if not errors:
    print(f"  \033[32m✅ ALL SCENARIO TESTS PASSED\033[0m")
else:
    print(f"  \033[31m❌ {len(errors)} test(s) FAILED:\033[0m")
    for e in errors:
        print(f"     • {e}")
print(f"{'='*55}\n")
sys.exit(0 if not errors else 1)
