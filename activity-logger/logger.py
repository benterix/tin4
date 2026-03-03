"""
Activity Logger
===============
Consumes three Redpanda (Kafka-compatible) topics and pretty-prints events.

Topics consumed (consumer group: tin4-activity-logger):
  - swipe_stream   → swipe actions
  - match_events   → match detections
  - user_activity  → logins, registrations, messages
"""
import asyncio
import json
import logging
import os
import signal

from aiokafka import AIOKafkaConsumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LOGGER] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

REDPANDA_BROKERS = os.getenv("REDPANDA_BROKERS", "redpanda:9092")
TOPICS = ["swipe_stream", "match_events", "user_activity"]
GROUP_ID = "tin4-activity-logger"

ICONS = {
    "swipe": "👈👉",
    "match": "💘",
    "login": "🔑",
    "register": "📝",
    "message_sent": "💬",
}


def format_event(topic: str, event: dict) -> str:
    event_type = event.get("event", topic)
    icon = ICONS.get(event_type, "📋")
    return f"{icon}  [{topic}] {json.dumps(event, ensure_ascii=False)}"


async def main():
    logger.info("Activity Logger starting, waiting for Redpanda…")

    consumer: AIOKafkaConsumer | None = None
    for attempt in range(20):
        try:
            consumer = AIOKafkaConsumer(
                *TOPICS,
                bootstrap_servers=REDPANDA_BROKERS,
                group_id=GROUP_ID,
                auto_offset_reset="earliest",
                value_deserializer=lambda v: json.loads(v.decode()),
            )
            await consumer.start()
            logger.info("Connected to Redpanda, consuming topics: %s", TOPICS)
            break
        except Exception as exc:
            logger.warning("Redpanda connect attempt %d: %s", attempt + 1, exc)
            consumer = None
            await asyncio.sleep(3)
    else:
        logger.error("Cannot connect to Redpanda — exiting")
        return

    stop = asyncio.get_running_loop().create_future()

    def _shutdown():
        if not stop.done():
            stop.set_result(None)

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, _shutdown)
    loop.add_signal_handler(signal.SIGINT, _shutdown)

    async def consume():
        async for msg in consumer:
            try:
                logger.info(format_event(msg.topic, msg.value))
            except Exception as exc:
                logger.error("Error processing message: %s", exc)

    consume_task = asyncio.create_task(consume())
    await stop
    consume_task.cancel()

    logger.info("Activity Logger shutting down")
    await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
