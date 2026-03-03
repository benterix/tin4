# TIN4 — Tinder-Like Educational Demo: Implementation Plan

## Overview

A Proof-of-Concept / MVP of a Tinder-like app designed for educational demonstration of a broad set of modern backend and networking technologies. Every major feature is deliberately wired to a specific technology to make the usage clear and instructive.

**Public hostname:** `37.27.16.14.nip.io`
**TLS:** Let's Encrypt via Traefik (HTTP-01 challenge)
**Primary language:** Python
**Orchestration:** Docker Compose

---

## Technology → Feature Mapping

| Technology         | Role in the App                                                    |
|--------------------|--------------------------------------------------------------------|
| TCP Socket Server  | Presence/heartbeat service — clients ping to signal "online"       |
| REST API (HTTPS)   | Core CRUD: auth, profiles, swipe actions, match listing            |
| WebSockets         | Real-time push: match notifications + live chat                    |
| GraphQL            | Flexible profile queries, user stats, match exploration            |
| RabbitMQ           | Async swipe-event processing and match-notification dispatch       |
| Redpanda (Kafka)   | Event streaming: activity logs, swipe stream, analytics topics     |

---

## Architecture

```
Browser / Demo Client
        │
        ▼
  ┌──────────────┐   HTTPS/WSS   ┌──────────────────────────────────────┐
  │   Traefik    │◄─────────────►│             FastAPI (api)            │
  │ (TLS + proxy)│               │  REST  │  WebSocket  │  GraphQL      │
  └──────────────┘               └────────┬─────────────┬───────────────┘
                                          │             │
                           ┌──────────────┘             └──────────────┐
                           ▼                                           ▼
                    ┌─────────────┐                           ┌──────────────┐
                    │  RabbitMQ   │                           │    Redis     │
                    └──────┬──────┘                           │(sessions,    │
                           │                                  │ presence,    │
                    ┌──────▼──────┐                           │ cache)       │
                    │   Match     │                           └──────────────┘
                    │  Processor  │◄──────────────────────────────────────────
                    └──────┬──────┘        reads presence / writes matches
                           │ publishes match event
                           ▼
                    ┌─────────────┐        ┌──────────────┐
                    │  Redpanda   │        │  PostgreSQL  │
                    │  (Kafka)    │        │  (main DB)   │
                    └──────┬──────┘        └──────────────┘
                           │
                    ┌──────▼──────┐
                    │  Activity   │
                    │   Logger    │
                    └─────────────┘

  ┌──────────────┐  TCP (port 9000)
  │  TCP Server  │◄──── raw socket heartbeat from browser JS (via TCP proxy)
  │  (presence)  │      or demo CLI client
  └──────────────┘
```

---

## Services (Docker Compose)

| Service            | Image / Build           | Ports (internal) | Exposed via Traefik          |
|--------------------|-------------------------|------------------|------------------------------|
| `traefik`          | traefik:v3              | 80, 443, 8080    | public 80/443                |
| `api`              | build: ./api            | 8000             | https://37.27.16.14.nip.io   |
| `tcp-server`       | build: ./tcp-server     | 9000             | tcp passthrough 9000         |
| `match-processor`  | build: ./match-processor| —                | internal only                |
| `activity-logger`  | build: ./activity-logger| —                | internal only                |
| `frontend`         | build: ./frontend       | 80               | https://37.27.16.14.nip.io/  |
| `rabbitmq`         | rabbitmq:3-management   | 5672, 15672      | mgmt UI optional             |
| `redpanda`         | redpandadata/redpanda   | 9092             | internal only                |
| `postgres`         | postgres:16             | 5432             | internal only                |
| `redis`            | redis:7                 | 6379             | internal only                |

---

## Feature Flows

### 1. User Registration & Login — REST API
- `POST /api/auth/register` → creates user, hashes password (bcrypt)
- `POST /api/auth/login` → returns JWT stored in Redis
- `GET /api/auth/me` → returns profile from JWT

### 2. Profile Browsing — GraphQL
- GraphQL endpoint at `POST /graphql`
- Query `profiles(limit, filters)` → returns candidate profiles not yet swiped
- Query `myMatches` → returns matched profiles with last message
- Query `stats` → total swipes, match rate, etc.
- Backed by PostgreSQL via SQLAlchemy async

### 3. Swipe Action — REST → RabbitMQ
- `POST /api/swipe` `{ target_id, direction: "like"|"pass" }`
- API writes swipe to PostgreSQL, then publishes `SwipeEvent` to RabbitMQ queue `swipe_events`
- Simultaneously publishes to Redpanda topic `swipe_stream`
- Returns `{ queued: true }` immediately (async processing)

### 4. Match Detection — RabbitMQ Consumer (match-processor)
- Consumes `swipe_events` queue
- Checks PostgreSQL: did `target_id` previously like `user_id`?
- If mutual like → insert Match row → publish `MatchEvent` to RabbitMQ `match_notifications`
- Also publishes `MatchEvent` to Redpanda topic `match_events`

### 5. Real-Time Notifications — WebSocket
- Client connects to `wss://37.27.16.14.nip.io/ws?token=<jwt>`
- API registers connection in an in-memory `ConnectionManager` (backed by Redis pub/sub for multi-instance safety)
- Match-processor publishes match notification to Redis pub/sub channel `matches:<user_id>`
- API WebSocket handler relays it to the live WebSocket connection
- Also used for real-time chat messages between matched users

### 6. Chat — WebSocket + REST
- `GET /api/matches/{match_id}/messages` — fetch history (REST)
- `POST /api/matches/{match_id}/messages` — send message (REST, stored in PG, published via WebSocket)
- Sending a message also publishes to Redpanda topic `user_activity`

### 7. Presence / Online Status — TCP Socket Server
- Standalone Python TCP server (`asyncio` + raw sockets) on port 9000
- Protocol: simple line-delimited JSON
  - Client sends: `{"action": "heartbeat", "token": "<jwt>"}\n` every 10s
  - Server responds: `{"status": "ok", "online_count": N}\n`
  - On disconnect: marks user offline in Redis
- API reads presence from Redis (`presence:<user_id>`) to show online indicators
- A demo CLI client (`tcp-server/client.py`) demonstrates the raw TCP connection

### 8. Activity Logging — Redpanda (Kafka) Consumer
- `activity-logger` service consumes topics: `swipe_stream`, `match_events`, `user_activity`
- Writes structured logs to stdout (JSON) — visible via `docker compose logs`
- Demonstrates Kafka consumer group pattern with offset management

---

## Project Directory Structure

```
tin4/
├── PLAN.md
├── docker-compose.yml
├── .env.example
├── traefik/
│   ├── traefik.yml           # static config: entrypoints, Let's Encrypt
│   └── acme.json             # cert storage (chmod 600)
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py               # FastAPI app, mounts REST + WS + GraphQL
│   ├── config.py             # settings via pydantic-settings
│   ├── database.py           # SQLAlchemy async engine + Base
│   ├── models.py             # User, Swipe, Match, Message ORM models
│   ├── auth.py               # JWT helpers, password hashing
│   ├── redis_client.py       # Redis connection pool
│   ├── rabbitmq_client.py    # aio-pika publisher
│   ├── kafka_client.py       # aiokafka producer
│   ├── ws_manager.py         # WebSocket ConnectionManager + Redis pub/sub
│   ├── routers/
│   │   ├── auth.py           # /api/auth/*
│   │   ├── profiles.py       # /api/profiles/*
│   │   ├── swipe.py          # /api/swipe
│   │   └── messages.py       # /api/matches/*/messages
│   └── graphql_schema.py     # Strawberry schema: queries + types
├── tcp-server/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── server.py             # asyncio TCP server (presence/heartbeat)
│   └── client.py             # demo CLI client (raw socket)
├── match-processor/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── processor.py          # RabbitMQ consumer → match detection
├── activity-logger/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── logger.py             # Redpanda/Kafka consumer → structured logging
└── frontend/
    ├── Dockerfile
    ├── nginx.conf
    └── static/
        ├── index.html        # single-page app shell
        ├── app.js            # vanilla JS: REST, WebSocket, GraphQL, TCP indicator
        └── style.css         # Tinder-like card swipe UI
```

---

## Key Dependencies (Python)

| Package             | Used in              | Purpose                                  |
|---------------------|----------------------|------------------------------------------|
| fastapi             | api                  | REST + WebSocket framework               |
| uvicorn             | api                  | ASGI server                              |
| strawberry-graphql  | api                  | GraphQL schema + FastAPI integration     |
| sqlalchemy[asyncio] | api, match-processor | Async ORM                                |
| asyncpg             | api, match-processor | PostgreSQL async driver                  |
| redis[asyncio]      | api, tcp-server      | Redis client                             |
| aio-pika            | api, match-processor | RabbitMQ async client (AMQP)             |
| aiokafka            | api, activity-logger | Kafka/Redpanda async producer/consumer   |
| python-jose         | api                  | JWT encode/decode                        |
| passlib[bcrypt]     | api                  | Password hashing                         |
| pydantic-settings   | all services         | Config from env vars                     |
| httpx               | (testing)            | Async HTTP client for tests              |

---

## Traefik & Let's Encrypt Configuration

- Traefik listens on ports 80 (HTTP, redirect to HTTPS) and 443 (HTTPS)
- HTTP-01 ACME challenge used (requires port 80 reachable on `37.27.16.14`)
- Certificate resolver named `letsencrypt` configured in `traefik.yml`
- `acme.json` mounted as a volume (must be `chmod 600`)
- API service gets label:
  ```
  traefik.http.routers.api.rule=Host(`37.27.16.14.nip.io`)
  traefik.http.routers.api.tls.certresolver=letsencrypt
  ```
- TCP port 9000 exposed directly (not via Traefik TLS — raw TCP for demo clarity)

---

## Data Models (PostgreSQL)

```
users         id, email, name, bio, age, photo_url, created_at
swipes        id, swiper_id → users, target_id → users, direction, created_at
matches       id, user1_id → users, user2_id → users, created_at
messages      id, match_id → matches, sender_id → users, body, created_at
```

---

## RabbitMQ Queues / Exchanges

| Exchange / Queue      | Type    | Producers          | Consumers        |
|-----------------------|---------|--------------------|------------------|
| `swipe_events`        | direct  | api (swipe router) | match-processor  |
| `match_notifications` | direct  | match-processor    | api (WS relay)   |

---

## Redpanda (Kafka) Topics

| Topic           | Producers                       | Consumers        | Purpose                  |
|-----------------|---------------------------------|------------------|--------------------------|
| `swipe_stream`  | api                             | activity-logger  | All swipe events stream  |
| `match_events`  | match-processor                 | activity-logger  | Match detection events   |
| `user_activity` | api (messages, login, register) | activity-logger  | General activity audit   |

---

## Implementation Phases

### Phase 1 — Infrastructure
1. Write `docker-compose.yml` with all services, networks, volumes
2. Write `traefik/traefik.yml` and configure Let's Encrypt
3. Add `.env.example` with all required variables
4. Verify Traefik comes up and issues cert for `37.27.16.14.nip.io`

### Phase 2 — Database & Core API
1. Write SQLAlchemy models and Alembic migrations (or `create_all` for MVP)
2. Implement auth (register, login, JWT)
3. Implement profile endpoints (REST)
4. Connect Redis session store

### Phase 3 — GraphQL
1. Define Strawberry types mirroring ORM models
2. Implement `profiles`, `myMatches`, `stats` queries
3. Mount at `/graphql` on the FastAPI app

### Phase 4 — Swipe & Async Processing
1. Implement `POST /api/swipe` with RabbitMQ publish (aio-pika)
2. Implement `match-processor` consumer
3. On match: write to DB, publish to `match_notifications` + Redpanda

### Phase 5 — WebSocket & Real-Time
1. Implement `ws_manager.py` with Redis pub/sub bridge
2. Add `/ws` endpoint to FastAPI
3. Match-processor publishes to Redis pub/sub → relayed to WebSocket clients

### Phase 6 — TCP Presence Server
1. Write `asyncio` TCP server in `tcp-server/server.py`
2. Protocol: newline-delimited JSON heartbeat
3. Store presence in Redis with TTL
4. Write `client.py` demo script
5. API `/api/profiles` enriches responses with presence data from Redis

### Phase 7 — Redpanda Activity Logger
1. Implement `activity-logger` Kafka consumer
2. Subscribe to all three topics, pretty-print JSON logs

### Phase 8 — Frontend
1. Single-page HTML/JS with card swipe UI
2. Demonstrates: REST login, GraphQL profile fetch, WebSocket match popup, TCP indicator

### Phase 9 — Hardening & Demo Polish
1. Seed script to populate fake users/profiles
2. README with `docker compose up` instructions and demo walkthrough
3. Diagram in README showing data flow per technology

---

## Environment Variables (.env.example)

```
DOMAIN=37.27.16.14.nip.io
ACME_EMAIL=admin@example.com

POSTGRES_DB=tin4
POSTGRES_USER=tin4
POSTGRES_PASSWORD=changeme
DATABASE_URL=postgresql+asyncpg://tin4:changeme@postgres:5432/tin4

REDIS_URL=redis://redis:6379/0

RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/

REDPANDA_BROKERS=redpanda:9092

JWT_SECRET=supersecretkey
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60*24

TCP_SERVER_HOST=0.0.0.0
TCP_SERVER_PORT=9000
```

---

## Notes for Educators / Presenters

- **TCP Server** is intentionally kept low-level (raw `asyncio` streams, no framework) to contrast with higher-level abstractions.
- **REST vs GraphQL** are both exposed on the same FastAPI app to show the difference: REST is resource-oriented, GraphQL allows arbitrary queries with a single endpoint.
- **RabbitMQ** models the classic work-queue / task pattern (exactly-once processing of swipe events).
- **Redpanda** models the event-log / analytics pattern (durable, replayable stream — consumers can replay from offset 0).
- **WebSockets** demonstrate stateful server-push vs stateless HTTP.
- All services are Python-first; only Traefik, RabbitMQ, Redpanda, PostgreSQL, and Redis are external images.
