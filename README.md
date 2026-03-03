# TIN4 — Tinder-Like Educational Tech Demo

A **proof-of-concept** Tinder-like app designed to demonstrate a wide range of modern backend and networking technologies in a single, cohesive project.

**Every major feature is intentionally wired to a specific technology** to make the educational mapping crystal-clear.

---

## Technology → Feature Map

| Technology | What it does here |
|---|---|
| **HTTPS REST API** (FastAPI) | Auth, profile browsing, swipe, matches, chat history |
| **WebSocket** | Real-time match notifications + live chat delivery |
| **GraphQL** (Strawberry) | Flexible profile queries, match exploration, user stats |
| **RabbitMQ** | Async swipe processing → match detection (work-queue pattern) |
| **Redpanda** (Kafka) | Event streaming: swipes, matches, activity audit log |
| **TCP Socket Server** | Presence/heartbeat service — raw asyncio sockets |

---

## Architecture

```
Browser
  │
  │  HTTPS/WSS
  ▼
Traefik (TLS + reverse proxy)
  │
  ├──/api/*  ──────────────────► FastAPI (api)
  │                                │  REST routers
  │                                │  WebSocket (/ws)
  │                                │  GraphQL (/graphql)
  │                                │
  ├──/graphql ────────────────────►│
  │                                │
  └──/ws ─────────────────────────►│
                                   │
                          ┌────────┴────────┐
                          │                 │
                       RabbitMQ          Redpanda
                          │                 │
                    Match Processor    Activity Logger
                          │                 │
                       Redis ◄─────────────►│
                          │
                     WebSocket push (match notifications)

TCP :9000 ◄── raw socket heartbeat ── demo client / tcp-server/client.py
         └──► Redis presence keys (read by REST /api/profiles)
```

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Domain `37.27.16.14.nip.io` pointing to your server (or `localhost` for local testing)

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env — set ACME_EMAIL for Let's Encrypt, change JWT_SECRET
```

### 2. Start the stack

```bash
docker compose up -d
```

First startup takes ~2 minutes for Redpanda to be ready.

### 3. Seed demo profiles

```bash
docker compose exec api python /app/seed.py
```

> Or copy `scripts/seed.py` into `api/seed.py` and run it. Seeds 20 fake profiles (password: `demo1234`).

### 4. Open the app

- **Frontend:** https://37.27.16.14.nip.io
- **API docs:** https://37.27.16.14.nip.io/api/docs
- **GraphQL:** https://37.27.16.14.nip.io/graphql
- **Traefik dashboard:** http://localhost:8088

---

## Demo TCP Client

The browser can't make raw TCP connections. Use the demo CLI client:

```bash
# Get a token first (login via API)
TOKEN=$(curl -s -X POST https://37.27.16.14.nip.io/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"alice@tin4.demo","password":"demo1234"}' | jq -r .access_token)

# Connect to TCP presence server
python tcp-server/client.py --host 37.27.16.14.nip.io --port 9000 --token $TOKEN
```

---

## API Reference

### Auth
| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/register` | Register new user |
| POST | `/api/auth/login` | Login, get JWT |
| GET | `/api/auth/me` | Get current user |

### Profiles
| Method | Path | Description |
|---|---|---|
| GET | `/api/profiles` | Get unswipped profiles |

### Swipe
| Method | Path | Description |
|---|---|---|
| POST | `/api/swipe` | `{target_id, direction: "like"\|"pass"}` |

### Matches & Chat
| Method | Path | Description |
|---|---|---|
| GET | `/api/matches` | List all matches |
| GET | `/api/matches/{id}/messages` | Chat history |
| POST | `/api/matches/{id}/messages` | Send message |

### GraphQL
```graphql
{ profiles(limit: 10) { id name age bio isOnline } }
{ myMatches { id otherUserId otherUserName } }
{ stats { totalSwipes likesSent matchesCount matchRate } }
```

### WebSocket
Connect to `wss://<domain>/ws?token=<jwt>`.

Messages received:
```json
{"type": "match", "data": {"match_id": "...", "other_user": {...}}}
{"type": "message", "data": {"match_id": "...", "message": {...}}}
```

---

## Data Flow: Swipe → Match → Notification

```
User swipes right
      │
      ▼
POST /api/swipe (REST)
      │
      ├──► PostgreSQL (write swipe record)
      ├──► RabbitMQ   queue: swipe_events
      └──► Redpanda   topic: swipe_stream

match-processor (RabbitMQ consumer):
      │  consumes swipe_events
      │  checks for mutual like in DB
      │  if match found:
      ├──► PostgreSQL  (write match record)
      ├──► Redis pub/sub channel: ws_events
      └──► Redpanda   topic: match_events

API (Redis pub/sub subscriber):
      │  receives ws_events message
      └──► WebSocket push → Browser
                  "💘 It's a match!"

activity-logger (Redpanda consumer):
      Logs all events from swipe_stream, match_events, user_activity
```

---

## Running Tests

### Unit & Integration Tests

```bash
cd tests
pip install -r requirements-test.txt
pip install aiosqlite  # for SQLite test DB

# API tests (no Docker needed, uses SQLite + mocks)
pytest test_auth.py test_swipe.py test_graphql.py -v

# TCP server tests
pytest test_tcp_server.py -v
```

### Playwright E2E Tests (requires full stack running)

```bash
playwright install chromium
pytest tests/playwright/test_e2e.py --base-url http://localhost -v
```

---

## Services

| Service | Container | Port |
|---|---|---|
| Traefik | tin4_traefik | 80, 443, 8088(dashboard) |
| FastAPI | tin4_api | 8000 (internal) |
| TCP Server | tin4_tcp | 9000 |
| Match Processor | tin4_match_processor | — |
| Activity Logger | tin4_activity_logger | — |
| Frontend (nginx) | tin4_frontend | 80 (internal) |
| RabbitMQ | tin4_rabbitmq | 5672, 15672 (internal) |
| Redpanda | tin4_redpanda | 9092 (internal) |
| PostgreSQL | tin4_postgres | 5432 (internal) |
| Redis | tin4_redis | 6379 (internal) |

---

## Educational Notes

- **TCP vs WebSocket**: The TCP server is intentionally low-level (raw `asyncio` streams) to contrast with the higher-level WebSocket abstraction.
- **RabbitMQ vs Redpanda**: RabbitMQ models **work-queue** (each message processed exactly once). Redpanda models **event log** (durable, replayable from offset 0).
- **REST vs GraphQL**: REST is resource-oriented and predictable. GraphQL allows the client to specify exactly what data it needs in a single request.
- **WebSocket relay**: Match notifications flow through `match-processor → Redis pub/sub → API WebSocket manager → browser`, demonstrating event-driven architecture across multiple services.

---

## Stack Versions

| Component | Version |
|---|---|
| Python | 3.12 |
| FastAPI | 0.115 |
| Strawberry GraphQL | 0.243 |
| SQLAlchemy | 2.0 (async) |
| aio-pika | 9.4 |
| aiokafka | 0.11 |
| RabbitMQ | 3.13 |
| Redpanda | 24.1 |
| PostgreSQL | 16 |
| Redis | 7 |
| Traefik | v3.0 |
