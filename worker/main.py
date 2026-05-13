import asyncio
import os
import redis.asyncio as aioredis


async def main():
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
    client = aioredis.from_url(redis_url)
    pubsub = client.pubsub()
    await pubsub.subscribe("analysis:trigger")
    print("Worker started, listening for analysis triggers...")
    async for message in pubsub.listen():
        if message["type"] == "message":
            print(f"Received trigger: {message['data']}")


if __name__ == "__main__":
    asyncio.run(main())
