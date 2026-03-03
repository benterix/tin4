import asyncio
import json
import logging

import aio_pika

from config import settings

logger = logging.getLogger(__name__)

_connection: aio_pika.RobustConnection | None = None
_channel: aio_pika.Channel | None = None


async def get_channel() -> aio_pika.Channel:
    global _connection, _channel
    if _connection is None or _connection.is_closed:
        for attempt in range(10):
            try:
                _connection = await aio_pika.connect_robust(settings.rabbitmq_url)
                break
            except Exception as exc:
                logger.warning("RabbitMQ connect attempt %d failed: %s", attempt + 1, exc)
                await asyncio.sleep(2)
        else:
            raise RuntimeError("Cannot connect to RabbitMQ")
    _channel = await _connection.channel()
    return _channel


async def publish(queue_name: str, payload: dict):
    channel = await get_channel()
    await channel.declare_queue(queue_name, durable=True)
    await channel.default_exchange.publish(
        aio_pika.Message(
            body=json.dumps(payload).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        ),
        routing_key=queue_name,
    )


async def close_rabbitmq():
    global _connection
    if _connection and not _connection.is_closed:
        await _connection.close()
