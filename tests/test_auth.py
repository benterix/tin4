"""Tests for authentication endpoints (REST API)."""
import pytest


@pytest.mark.asyncio
async def test_register_success(app_client):
    res = await app_client.post("/api/auth/register", json={
        "email": "alice@example.com",
        "name": "Alice",
        "password": "secret123",
        "age": 25,
        "bio": "Love hiking",
    })
    assert res.status_code == 201
    data = res.json()
    assert "access_token" in data
    assert "user_id" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email(app_client):
    payload = {
        "email": "bob@example.com",
        "name": "Bob",
        "password": "pass",
        "age": 30,
    }
    res1 = await app_client.post("/api/auth/register", json=payload)
    assert res1.status_code == 201

    res2 = await app_client.post("/api/auth/register", json=payload)
    assert res2.status_code == 400
    assert "already registered" in res2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_success(app_client):
    await app_client.post("/api/auth/register", json={
        "email": "carol@example.com",
        "name": "Carol",
        "password": "mypassword",
        "age": 28,
    })
    res = await app_client.post("/api/auth/login", json={
        "email": "carol@example.com",
        "password": "mypassword",
    })
    assert res.status_code == 200
    assert "access_token" in res.json()


@pytest.mark.asyncio
async def test_login_wrong_password(app_client):
    await app_client.post("/api/auth/register", json={
        "email": "dave@example.com",
        "name": "Dave",
        "password": "correct",
        "age": 35,
    })
    res = await app_client.post("/api/auth/login", json={
        "email": "dave@example.com",
        "password": "wrong",
    })
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_me_authenticated(app_client):
    reg = await app_client.post("/api/auth/register", json={
        "email": "eve@example.com",
        "name": "Eve",
        "password": "pass123",
        "age": 22,
        "bio": "Test bio",
    })
    token = reg.json()["access_token"]
    res = await app_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "eve@example.com"
    assert data["name"] == "Eve"
    assert data["age"] == 22


@pytest.mark.asyncio
async def test_me_unauthenticated(app_client):
    res = await app_client.get("/api/auth/me")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_health(app_client):
    res = await app_client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
