from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.redis import get_redis
from core.security import DUMMY_HASH, create_access_token, verify_password
from deps import get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    row = await db.execute(
        text("SELECT id, username, password_hash FROM users WHERE username = :username"),
        {"username": body.username},
    )
    user = row.mappings().first()

    # Always run bcrypt to prevent timing-based username enumeration.
    # Use the real hash when the user exists, a pre-computed dummy otherwise.
    candidate_hash = user["password_hash"] if user else DUMMY_HASH
    valid = verify_password(body.password, candidate_hash)

    if not user or not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    return TokenResponse(access_token=create_access_token(user["id"]))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: dict = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
):
    """Invalidate the bearer token by adding its jti to the Redis denylist."""
    jti = current_user.get("jti")
    exp = current_user.get("exp")
    if jti and exp:
        ttl = int(exp - datetime.now(timezone.utc).timestamp())
        if ttl > 0:
            await redis.setex(f"denylist:{jti}", ttl, "1")


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    return {"id": current_user["id"], "username": current_user["username"]}

