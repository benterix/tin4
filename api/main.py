import asyncio
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query as QParam
from fastapi.middleware.cors import CORSMiddleware

from auth import decode_token
from database import init_db
from graphql_schema import get_graphql_router
from kafka_client import close_kafka
from rabbitmq_client import close_rabbitmq
from redis_client import close_redis, get_redis
from routers.auth import router as auth_router
from routers.matches import router as matches_router
from routers.profiles import router as profiles_router
from routers.swipe import router as swipe_router
from ws_manager import connect, disconnect, redis_pubsub_listener

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="TIN4 — Tinder-Like Demo",
    description="Educational demo: REST · WebSocket · GraphQL · RabbitMQ · Redpanda · TCP",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── REST routers ──────────────────────────────────────────────────────────
app.include_router(auth_router, prefix="/api/auth")
app.include_router(profiles_router, prefix="/api")
app.include_router(swipe_router, prefix="/api")
app.include_router(matches_router, prefix="/api")

# ── GraphQL ───────────────────────────────────────────────────────────────
graphql_router = get_graphql_router(app.state)
# Inject user_id from Bearer token into request.state for GraphQL context
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class AuthStateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            user_id = decode_token(auth[7:])
            request.state.user_id = user_id
        else:
            request.state.user_id = None
        return await call_next(request)


app.add_middleware(AuthStateMiddleware)
app.include_router(graphql_router, prefix="/graphql")


# ── WebSocket endpoint ────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = QParam(default=None),
):
    if not token:
        await websocket.close(code=4001)
        return
    user_id = decode_token(token)
    if not user_id:
        await websocket.close(code=4001)
        return

    await connect(user_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # echo heartbeat pings back
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        disconnect(user_id)


# ── Health ────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "tin4-api"}


# ── Lifecycle ─────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info("Initialising database…")
    await init_db()
    logger.info("Starting Redis pub/sub listener…")
    asyncio.create_task(redis_pubsub_listener())
    logger.info("API ready")


@app.on_event("shutdown")
async def shutdown():
    await close_redis()
    await close_rabbitmq()
    await close_kafka()
