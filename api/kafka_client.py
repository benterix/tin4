import asyncio
import json
import logging

from aiokafka import AIOKafkaProducer

from config import settings

logger = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None


async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        for attempt in range(15):
            try:
                _producer = AIOKafkaProducer(
                    bootstrap_servers=settings.redpanda_brokers,
                    value_serializer=lambda v: json.dumps(v).encode(),
                )
                await _producer.start()
                logger.info("Kafka/Redpanda producer connected")
                break
            except Exception as exc:
                logger.warning("Kafka connect attempt %d failed: %s", attempt + 1, exc)
                _producer = None
                await asyncio.sleep(3)
        else:
            raise RuntimeError("Cannot connect to Redpanda")
    return _producer


async def produce(topic: str, value: dict):
    try:
        producer = await get_producer()
        await producer.send_and_wait(topic, value)
    except Exception as exc:
        logger.error("Failed to produce to %s: %s", topic, exc)


async def close_kafka():
    global _producer
    if _producer:
        await _producer.stop()
        _producer = None
