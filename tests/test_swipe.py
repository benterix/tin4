"""Tests for swipe and match endpoints."""
import pytest


async def register_user(client, email, name, age=25):
    res = await client.post("/api/auth/register", json={
        "email": email, "name": name, "password": "pass123", "age": age,
    })
    assert res.status_code == 201
    return res.json()


@pytest.mark.asyncio
async def test_swipe_like(app_client):
    u1 = await register_user(app_client, "swiper1@test.com", "Swiper1")
    u2 = await register_user(app_client, "target1@test.com", "Target1")
    token = u1["access_token"]

    res = await app_client.post("/api/swipe",
        json={"target_id": u2["user_id"], "direction": "like"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 202
    data = res.json()
    assert data["queued"] is True
    assert "swipe_id" in data


@pytest.mark.asyncio
async def test_swipe_pass(app_client):
    u1 = await register_user(app_client, "swiper2@test.com", "Swiper2")
    u2 = await register_user(app_client, "target2@test.com", "Target2")
    token = u1["access_token"]

    res = await app_client.post("/api/swipe",
        json={"target_id": u2["user_id"], "direction": "pass"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 202


@pytest.mark.asyncio
async def test_swipe_duplicate(app_client):
    u1 = await register_user(app_client, "swiper3@test.com", "Swiper3")
    u2 = await register_user(app_client, "target3@test.com", "Target3")
    token = u1["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    await app_client.post("/api/swipe",
        json={"target_id": u2["user_id"], "direction": "like"}, headers=headers)
    res = await app_client.post("/api/swipe",
        json={"target_id": u2["user_id"], "direction": "like"}, headers=headers)
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_swipe_self(app_client):
    u1 = await register_user(app_client, "swiper4@test.com", "Swiper4")
    token = u1["access_token"]
    res = await app_client.post("/api/swipe",
        json={"target_id": u1["user_id"], "direction": "like"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_swipe_invalid_direction(app_client):
    u1 = await register_user(app_client, "swiper5@test.com", "Swiper5")
    u2 = await register_user(app_client, "target5@test.com", "Target5")
    token = u1["access_token"]
    res = await app_client.post("/api/swipe",
        json={"target_id": u2["user_id"], "direction": "superlike"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_profiles_excludes_swiped(app_client):
    u1 = await register_user(app_client, "viewer@test.com", "Viewer")
    u2 = await register_user(app_client, "visible@test.com", "Visible", age=26)
    token = u1["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Before swipe, visible user should appear
    res = await app_client.get("/api/profiles", headers=headers)
    assert res.status_code == 200
    ids = [p["id"] for p in res.json()]
    assert u2["user_id"] in ids

    # Swipe
    await app_client.post("/api/swipe",
        json={"target_id": u2["user_id"], "direction": "pass"}, headers=headers)

    # After swipe, visible user should NOT appear
    res2 = await app_client.get("/api/profiles", headers=headers)
    ids2 = [p["id"] for p in res2.json()]
    assert u2["user_id"] not in ids2


@pytest.mark.asyncio
async def test_matches_empty_initially(app_client):
    u = await register_user(app_client, "matchless@test.com", "Matchless")
    token = u["access_token"]
    res = await app_client.get("/api/matches", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json() == []
