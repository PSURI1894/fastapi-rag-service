"""Auth endpoints.

    POST /auth/token -> exchange username+password for a JWT (the login route)
    GET  /auth/me    -> return the current user (a protected route, for demoing)

`/auth/token` follows the OAuth2 password-grant convention exactly, which is why
the /docs "Authorize" button just works: it posts here behind the scenes and
remembers the returned token for subsequent calls.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.config import Settings, get_settings
from app.dependencies import get_user_repository
from app.repositories.users import UserRepository
from app.schemas import Token, UserPublic
from app.security import authenticate_user, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=Token)
async def login(
    # OAuth2PasswordRequestForm reads `username` and `password` from form-encoded
    # body (not JSON) — that's the OAuth2 spec. `Depends()` builds it from the request.
    form_data: OAuth2PasswordRequestForm = Depends(),
    repo: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> Token:
    user = await authenticate_user(repo, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(subject=user.username, settings=settings)
    return Token(access_token=access_token)


@router.get("/me", response_model=UserPublic)
async def read_me(current_user: UserPublic = Depends(get_current_user)) -> UserPublic:
    # If the token is missing/invalid, get_current_user raises 401 before we get here.
    return current_user
