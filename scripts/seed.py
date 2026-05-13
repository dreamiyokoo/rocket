"""初期データ投入: usersテーブルに入力者1名を登録する"""
import asyncio
import os

import asyncpg
from passlib.context import CryptContext

DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
SEED_USERNAME = os.getenv("SEED_USERNAME", "admin")
SEED_PASSWORD = os.getenv("SEED_PASSWORD", "changeme")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def main() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        existing = await conn.fetchval("SELECT id FROM users WHERE username = $1", SEED_USERNAME)
        if existing:
            print(f"User '{SEED_USERNAME}' already exists, skipping.")
            return
        hashed = pwd_context.hash(SEED_PASSWORD)
        await conn.execute(
            "INSERT INTO users (username, password_hash) VALUES ($1, $2)",
            SEED_USERNAME,
            hashed,
        )
        print(f"Created user '{SEED_USERNAME}'.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
