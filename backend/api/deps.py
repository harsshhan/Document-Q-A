"""Shared FastAPI dependencies."""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import TokenError, decode_access_token
from db.models import User
from db.session import get_session
from services.users import get_user_by_id

# auto_error=False so we control the 401 response (and its WWW-Authenticate header).
bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Validate the Bearer token and return the matching user.

    Every protected route depends on this, so a request can only ever act as the
    user identified by its own token - never as a user id supplied by the client.
    """

    if credentials is None or not credentials.credentials:
        raise _unauthorized("Not authenticated")

    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise _unauthorized(str(exc)) from exc

    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (TypeError, ValueError) as exc:
        raise _unauthorized("Token is invalid.") from exc

    user = await get_user_by_id(session, user_id)
    if user is None:
        raise _unauthorized("Token is invalid.")

    return user
