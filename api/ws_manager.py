"""
WebSocket connection manager.

Each authenticated user can have one active WebSocket connection.
When a match or message event is published to Redis pub/sub channel
`ws:<user_id>`, the manager relays the JSON payload to the live socket.
"""
import asyncio
import json
import logging
from typing import Dict

from fastapi import WebSocket

from redis_client import get_redis

logger = logging.getLogger(__name__)

# user_id -> WebSocket
_connections: Dict[str, WebSocket] = {}


async def connect(user_id: str, websocket: WebSocket):
    await websocket.accept()
    _connections[user_id] = websocket
    logger.info("WS connected: %s (total=%d)", user_id, len(_connections))


def disconnect(user_id: str):
    _connections.pop(user_id, None)
    logger.info("WS disconnected: %s (total=%d)", user_id, len(_connections))


async def send_to_user(user_id: str, payload: dict):
    ws = _connections.get(user_id)
    if ws:
        try:
            await ws.send_json(payload)
        except Exception as exc:
            logger.warning("WS send failed for %s: %s", user_id, exc)
            disconnect(user_id)


async def broadcast(payload: dict):
    for uid, ws in list(_connections.items()):
        try:
            await ws.send_json(payload)
        except Exception:
            disconnect(uid)


async def redis_pubsub_listener():
    """
    Background task: subscribes to Redis channel `ws_events` and
    relays published messages to connected WebSocket clients.
    Message format: {"user_id": "...", "payload": {...}}
    """
    redis = await get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe("ws_events")
    logger.info("Redis pub/sub listener started on channel 'ws_events'")
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                data = json.loads(message["data"])
                user_id = data.get("user_id")
                payload = data.get("payload", {})
                if user_id:
                    await send_to_user(user_id, payload)
            except Exception as exc:
                logger.error("pub/sub relay error: %s", exc)
    finally:
        await pubsub.unsubscribe("ws_events")
