"""Authentication routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from api.schemas import LoginRequest, RegisterRequest, TokenResponse, UserPublic
from core.security import create_access_token, hash_password, verify_password
from db.models import User
from db.session import get_session
from services.users import get_user_by_email, get_user_by_username

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
)
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> User:
    if await get_user_by_username(session, payload.username) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is already taken.",
        )

    if await get_user_by_email(session, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered.",
        )

    user = User(
        name=payload.name,
        username=payload.username,
        email=str(payload.email),
        password_hash=hash_password(payload.password),
    )
    session.add(user)

    try:
        await session.commit()
    except IntegrityError as exc:
        # Guards against two concurrent registrations for the same identity.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email is already registered.",
        ) from exc

    await session.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse, summary="Log in")
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    user = await get_user_by_username(session, payload.username)

    if user is None or not verify_password(payload.password, user.password_hash):
        # Same message for unknown user and wrong password: no account enumeration.
        # The password is never logged.
        logger.info("Failed login attempt for username=%s", payload.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    token, expires_in = create_access_token(str(user.id))

    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserPublic.model_validate(user),
    )


@router.get("/me", response_model=UserPublic, summary="Current user profile")
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
