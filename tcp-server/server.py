"""
Bespoke TCP Presence Server
===========================
Demonstrates raw asyncio TCP socket programming.

Protocol (newline-delimited JSON over TCP):
  Client → Server  {"action": "heartbeat", "token": "<jwt>"}
  Server → Client  {"status": "ok", "user_id": "...", "online_count": N}

  Client → Server  {"action": "disconnect"}
  Server → Client  {"status": "bye"}

The server stores presence in Redis with a TTL. Each heartbeat resets the TTL.
"""
import asyncio
import json
import logging
import os
import signal

import redis.asyncio as aioredis
from jose import JWTError, jwt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [TCP] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
JWT_SECRET = os.getenv("JWT_SECRET", "supersecretkey_change_in_production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
PORT = int(os.getenv("TCP_SERVER_PORT", "9000"))
PRESENCE_TTL = 30  # seconds

_redis: aioredis.Redis | None = None
_active_users: set[str] = set()


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    logger.info("New connection from %s", peer)
    user_id: str | None = None

    try:
        while True:
            raw = await asyncio.wait_for(reader.readline(), timeout=60)
            if not raw:
                break
            try:
                msg = json.loads(raw.decode().strip())
            except json.JSONDecodeError:
                writer.write(b'{"error": "invalid json"}\n')
                await writer.drain()
                continue

            action = msg.get("action")

            if action == "heartbeat":
                token = msg.get("token", "")
                uid = decode_token(token)
                if not uid:
                    writer.write(b'{"error": "invalid token"}\n')
                    await writer.drain()
                    continue

                user_id = uid
                _active_users.add(user_id)
                redis = await get_redis()
                await redis.setex(f"presence:{user_id}", PRESENCE_TTL, "1")
                online_count = len(_active_users)

                response = json.dumps({
                    "status": "ok",
                    "user_id": user_id,
                    "online_count": online_count,
                }) + "\n"
                writer.write(response.encode())
                await writer.drain()
                logger.debug("Heartbeat from %s (%s)", user_id, peer)

            elif action == "disconnect":
                writer.write(b'{"status": "bye"}\n')
                await writer.drain()
                break

            else:
                writer.write(b'{"error": "unknown action"}\n')
                await writer.drain()

    except asyncio.TimeoutError:
        logger.info("Client %s timed out", peer)
    except ConnectionResetError:
        logger.info("Client %s reset connection", peer)
    finally:
        if user_id:
            _active_users.discard(user_id)
            try:
                redis = await get_redis()
                await redis.delete(f"presence:{user_id}")
            except Exception:
                pass
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        logger.info("Connection closed: %s", peer)


async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", PORT)
    addr = server.sockets[0].getsockname()
    logger.info("TCP Presence Server listening on %s:%d", addr[0], addr[1])

    loop = asyncio.get_running_loop()
    stop = loop.create_future()

    def _shutdown():
        if not stop.done():
            stop.set_result(None)

    loop.add_signal_handler(signal.SIGTERM, _shutdown)
    loop.add_signal_handler(signal.SIGINT, _shutdown)

    async with server:
        await stop

    logger.info("TCP server shutting down")


if __name__ == "__main__":
    asyncio.run(main())
