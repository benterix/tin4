"""Tests for GraphQL endpoint."""
import pytest


async def register_and_token(client, suffix="gql"):
    res = await client.post("/api/auth/register", json={
        "email": f"gqluser_{suffix}@test.com",
        "name": f"GQLUser {suffix}",
        "password": "pass123",
        "age": 27,
    })
    assert res.status_code == 201
    return res.json()["access_token"]


@pytest.mark.asyncio
async def test_graphql_profiles(app_client):
    token = await register_and_token(app_client, "a")
    res = await app_client.post(
        "/graphql",
        json={"query": "{ profiles(limit: 5) { id name age bio isOnline } }"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "data" in data
    assert "profiles" in data["data"]
    assert isinstance(data["data"]["profiles"], list)


@pytest.mark.asyncio
async def test_graphql_my_matches(app_client):
    token = await register_and_token(app_client, "b")
    res = await app_client.post(
        "/graphql",
        json={"query": "{ myMatches { id otherUserId otherUserName } }"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "myMatches" in data["data"]
    assert isinstance(data["data"]["myMatches"], list)


@pytest.mark.asyncio
async def test_graphql_stats(app_client):
    token = await register_and_token(app_client, "c")
    res = await app_client.post(
        "/graphql",
        json={"query": "{ stats { totalSwipes likesSent passesSent matchesCount matchRate } }"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    stats = data["data"]["stats"]
    assert stats["totalSwipes"] == 0
    assert stats["likesSent"] == 0
    assert stats["matchRate"] == 0.0


@pytest.mark.asyncio
async def test_graphql_stats_after_swipe(app_client):
    t1 = await register_and_token(app_client, "d1")
    r2 = await app_client.post("/api/auth/register", json={
        "email": "gqluser_d2@test.com", "name": "D2", "password": "p", "age": 28
    })
    u2_id = r2.json()["user_id"]

    await app_client.post("/api/swipe",
        json={"target_id": u2_id, "direction": "like"},
        headers={"Authorization": f"Bearer {t1}"},
    )

    res = await app_client.post(
        "/graphql",
        json={"query": "{ stats { totalSwipes likesSent } }"},
        headers={"Authorization": f"Bearer {t1}"},
    )
    stats = res.json()["data"]["stats"]
    assert stats["totalSwipes"] == 1
    assert stats["likesSent"] == 1


@pytest.mark.asyncio
async def test_graphql_unauthenticated_returns_empty(app_client):
    """GraphQL returns empty lists (not error) for unauthenticated users."""
    res = await app_client.post(
        "/graphql",
        json={"query": "{ profiles(limit: 5) { id } }"},
    )
    assert res.status_code == 200
    assert res.json()["data"]["profiles"] == []
