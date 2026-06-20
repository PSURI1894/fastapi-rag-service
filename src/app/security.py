"""Authentication: password hashing, JWT issuing/verifying, and the
`get_current_user` dependency.

The flow this file implements (OAuth2 "password" grant):

    1. Client POSTs username+password to /auth/token.
    2. We look the user up and `verify_password` against the stored Argon2 hash.
    3. On success we `create_access_token` — a JWT signed with our secret, carrying
       the username in `sub` and an expiry in `exp`.
    4. Client sends that token on every later request: `Authorization: Bearer ...`.
    5. `get_current_user` (a dependency) decodes + verifies the token and loads the
       user. Any protected route just declares `Depends(get_current_user)`.

Nothing is stored server-side between requests — the signed token IS the session.
That statelessness is why JWT scales horizontally.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash

from app.config import Settings, get_settings
from app.dependencies import get_user_repository
from app.repositories.users import User, UserRepository
from app.schemas import UserPublic

# Argon2 hasher (via pwdlib's recommended config). Hashing is intentionally slow,
# which is what makes brute-forcing stolen hashes expensive.
_password_hash = PasswordHash.recommended()

# Declaring this scheme does two things: it pulls the bearer token out of the
# Authorization header, AND it wires up the "Authorize" button in /docs.
# tokenUrl points at our login route so the docs know where to get a token.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


def hash_password(plain: str) -> str:
    return _password_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _password_hash.verify(plain, hashed)


def create_access_token(subject: str, settings: Settings) -> str:
    """Sign a JWT whose `sub` is the username and which expires after the
    configured number of minutes. pyjwt encodes the `exp` datetime to a UNIX
    timestamp and enforces it automatically on decode."""
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


async def authenticate_user(
    repo: UserRepository, username: str, password: str
) -> User | None:
    """Return the user iff the username exists and the password matches."""
    user = await repo.get_by_username(username)
    if user is None:
        # Note: a hardened version would still run verify_password against a dummy
        # hash here to keep response timing constant (defeats user enumeration).
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    settings: Settings = Depends(get_settings),
    repo: UserRepository = Depends(get_user_repository),
) -> UserPublic:
    """Decode + verify the bearer token, then load the user it names.

    Every failure mode (bad signature, expired, malformed, unknown user) collapses
    to one generic 401 — never tell an attacker *why* a token was rejected.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise credentials_exception from None

    username = payload.get("sub")
    if not isinstance(username, str):
        raise credentials_exception

    user = await repo.get_by_username(username)
    if user is None:
        raise credentials_exception
    if user.disabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

    return UserPublic(username=user.username, full_name=user.full_name, disabled=user.disabled)
