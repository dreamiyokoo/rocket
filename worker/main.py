import asyncio
import os
import signal
import redis.asyncio as aioredis


async def main():
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
    client = aioredis.from_url(redis_url)
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe("analysis:trigger")
        print("Worker started, listening for analysis triggers...")
        async for message in pubsub.listen():
            if message["type"] == "message":
                print(f"Received trigger: {message['data']}")
    finally:
        await pubsub.unsubscribe("analysis:trigger")
        await pubsub.aclose()
        await client.aclose()


def _handle_signal(loop: asyncio.AbstractEventLoop) -> None:
    """Stop the event loop on SIGINT or SIGTERM for clean shutdown."""
    loop.stop()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, loop)
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
