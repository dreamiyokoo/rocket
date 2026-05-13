import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError
from passlib.context import CryptContext

from core.config import settings

JWT_ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Pre-computed bcrypt hash used on the "user not found" path to prevent
# timing-based username enumeration (always run bcrypt regardless of outcome).
DUMMY_HASH: str = pwd_context.hash("__dummy_timing_guard__")


class TokenExpiredError(Exception):
    """Raised when the JWT has expired."""


class TokenInvalidError(Exception):
    """Raised when the JWT is malformed or has an invalid signature."""


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: int) -> str:
    """Create a JWT with the user's stable ID as `sub` and a unique `jti`."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire, "jti": str(uuid.uuid4())},
        settings.JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def decode_token(token: str) -> dict:
    """Decode and verify a JWT.

    Returns the full payload dict on success.
    Raises TokenExpiredError for expired tokens.
    Raises TokenInvalidError for any other failure.
    """
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired") from exc
    except JWTError as exc:
        raise TokenInvalidError("Invalid token") from exc

