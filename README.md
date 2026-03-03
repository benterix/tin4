# TIN4 — Tinder-Like Educational Tech Demo

A **proof-of-concept** Tinder-like app designed to demonstrate a wide range of modern backend and networking technologies in a single, cohesive project.

**Every major feature is intentionally wired to a specific technology** to make the educational mapping crystal-clear.

**Live demo:** https://37.27.16.14.nip.io (Let's Encrypt TLS)

---

## Technology → Feature Map

| Technology | What it does here |
|---|---|
| **HTTPS REST API** (FastAPI) | Auth, profile browsing, swipe, matches, chat history |
| **WebSocket** | Real-time match notifications + live chat delivery |
| **GraphQL** (Strawberry) | Flexible profile queries, match exploration, user stats |
| **RabbitMQ** | Async swipe processing → match detection (work-queue pattern) |
| **Redpanda** (Kafka) | Event streaming: swipes, matches, activity audit log |
| **TCP Socket Server** | Presence/heartbeat service — raw asyncio sockets on port 9000 |

---

## Architecture

```
Browser
  │
  │  HTTPS/WSS
  ▼
Traefik v2.11 (TLS + reverse proxy)
  │
  ├──/api/*  ──────────────────► FastAPI (api:8000)
  │                                │  REST routers
  │                                │  WebSocket (/ws)
  │                                │  GraphQL (/graphql)
  │
  └──/  ───────────────────────► nginx (frontend:80)
                                   └── proxies /api /graphql /ws → api

                          ┌────────┴────────┐
                          │                 │
                       RabbitMQ          Redpanda
                          │                 │
                    Match Processor    Activity Logger
                          │
                       Redis pub/sub
                          │
                     WebSocket push → Browser ("💘 It's a match!")

TCP :9000 ◄── raw socket heartbeat ── tcp-server/client.py
         └──► Redis presence keys (TTL 30s, read by /api/profiles)
```

---

## Quick Start

### Prerequisites
- Docker Engine 24+ and Docker Compose
- A public domain / nip.io address for Let's Encrypt (or use `localhost` for local testing)

### 1. Configure environment

```bash
cp .env.example .env
# Set DOMAIN, ACME_EMAIL (must be a real domain, not example.com), JWT_SECRET
```

### 2. Start the stack

```bash
docker compose up -d
```

First startup takes ~2 minutes for Redpanda to be ready. All 10 services should reach healthy status.

### 3. Seed demo profiles

```bash
docker compose exec api python /app/seed.py
```

Seeds 20 profiles with AI-generated photos (see below). Password for all: `demo1234`.

### 4. Open the app

| URL | Description |
|---|---|
| https://37.27.16.14.nip.io | Frontend SPA |
| https://37.27.16.14.nip.io/api/docs | FastAPI Swagger UI |
| https://37.27.16.14.nip.io/graphql | GraphQL playground |
| http://localhost:8088 | Traefik dashboard |
| http://localhost:8081 | Frontend (direct, bypasses Traefik) |
| http://localhost:8000/docs | API (direct, bypasses Traefik) |

---

## Test Users

See `testusers.txt` for full list. All share password `demo1234`:

| Email | Name | Age | Bio |
|---|---|---|---|
| alice@tin4.demo | Alice | 26 | Coffee addict & hiker |
| bob@tin4.demo | Bob | 29 | Software engineer by day, chef by night |
| carol@tin4.demo | Carol | 24 | Yoga instructor who loves jazz |
| dave@tin4.demo | Dave | 31 | Marathon runner |
| eve@tin4.demo | Eve | 27 | Data scientist & amateur astronomer |
| ... | (16 more in testusers.txt) | | |

Profile photos are **AI-generated** via [ImageRouter](https://imagerouter.io) using `black-forest-labs/FLUX-2-max` (SOTA quality, 1024×1024) — 20 images for $1.40 total. Each prompt is tailored to the user's bio/occupation.

---

## Demo TCP Client

The browser can't make raw TCP connections. Use the CLI client:

```bash
# Get a JWT first
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

### Profiles & Swipe
| Method | Path | Description |
|---|---|---|
| GET | `/api/profiles?limit=N` | Browse unswiped profiles |
| POST | `/api/swipe` | `{target_id, direction: "like"\|"pass"}` |

### Matches & Chat
| Method | Path | Description |
|---|---|---|
| GET | `/api/matches` | List all matches |
| GET | `/api/matches/{id}/messages` | Chat history |
| POST | `/api/matches/{id}/messages` | Send message (body min 1 char) |

### GraphQL
```graphql
{ profiles(limit: 10) { id name age bio isOnline } }
{ myMatches { id otherUserId otherUserName } }
{ stats { totalSwipes likesSent matchesCount matchRate } }
```

### WebSocket
Connect: `wss://<domain>/ws?token=<jwt>`

Events received:
```json
{"type": "match",   "data": {"match_id": "...", "other_user": {...}}}
{"type": "message", "data": {"match_id": "...", "message": {...}}}
```

---

## Data Flow: Swipe → Match → Notification

```
POST /api/swipe
  ├─► PostgreSQL      write swipe record
  ├─► RabbitMQ        queue: swipe_events  (fire-and-forget)
  └─► Redpanda        topic: swipe_stream  (fire-and-forget)

match-processor (RabbitMQ consumer):
  reads swipe_events → checks mutual like in DB
  if match:
    ├─► PostgreSQL    write match record
    ├─► Redis pub/sub channel: ws_events
    └─► Redpanda      topic: match_events

API WS manager (Redis subscriber):
  receives ws_events → pushes to connected WebSocket client

activity-logger (Redpanda consumer):
  logs swipe_stream + match_events + user_activity
```

---

## Running Tests

### Unit Tests (no Docker needed — uses SQLite + mocks)

```bash
pip install -r tests/requirements-test.txt pydantic-settings aio-pika aiokafka asyncpg
pytest tests/ --ignore=tests/playwright -v
# 24 tests, all passing
```

### Playwright E2E (requires full stack)

```bash
playwright install chromium
pytest tests/playwright/test_e2e.py --base-url http://localhost:8081 -v
# 12 tests, all passing
```

### Scenario Tests (against live HTTPS stack)

```bash
python3 scripts/scenario_test.py https://37.27.16.14.nip.io
# 44 checks across 16 user scenarios, all passing
```

---

## Services

| Container | Role | Exposed port |
|---|---|---|
| tin4_traefik | Reverse proxy + TLS | 80, 443, 8088 (dashboard) |
| tin4_api | FastAPI — REST + WS + GraphQL | 8000 |
| tin4_tcp | TCP presence server | 9000 |
| tin4_frontend | nginx SPA + API proxy | 8081 |
| tin4_match_processor | RabbitMQ consumer | — |
| tin4_activity_logger | Redpanda consumer | — |
| tin4_rabbitmq | Message broker | internal |
| tin4_redpanda | Kafka-compatible event log | internal |
| tin4_postgres | Primary database | internal |
| tin4_redis | Cache + pub/sub | internal |

---

## Key Design Decisions

- **Traefik v2.11** (not v3): Docker Engine 27+ dropped support for Docker API < 1.44 which Traefik v3.0's embedded client used, breaking Docker label routing entirely.
- **Fire-and-forget publishes**: Swipe endpoint uses `asyncio.create_task()` for RabbitMQ/Redpanda publishes so HTTP responses never block on broker availability.
- **UUID columns in match-processor**: Must use `Column(UUID(as_uuid=False))` not `Column(String)` — asyncpg is strict about type coercion.
- **Redis pub/sub relay**: Multi-instance WebSocket support: any API instance can deliver a notification to any connected user.

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
| Traefik | v2.11 |
