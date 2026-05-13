import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

from core.config import settings

JWT_ALGORITHM = "HS256"

# Pre-computed bcrypt hash used on the "user not found" path to prevent
# timing-based username enumeration (always run bcrypt regardless of outcome).
DUMMY_HASH: str = bcrypt.hashpw(b"__dummy__", bcrypt.gensalt()).decode()


class TokenExpiredError(Exception):
    pass


class TokenInvalidError(Exception):
    pass


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire, "jti": str(uuid.uuid4())},
        settings.JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired") from exc
    except JWTError as exc:
        raise TokenInvalidError("Invalid token") from exc
