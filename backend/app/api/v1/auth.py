import os

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from backend.app.core.auth import (
    SESSION_COOKIE,
    get_current_user,
    require_demo_auth_enabled,
)
from backend.app.core.demo_auth import (
    DEMO_USERS,
    SESSION_TTL_SECONDS,
    DemoUser,
    DemoUserId,
    create_session,
    delete_session,
    get_session_user,
)
from backend.app.storage.audit import AuditLog

router = APIRouter(prefix="/auth", tags=["authentication"])


class DemoLoginRequest(BaseModel):
    user_id: DemoUserId


def _cookie_secure(request: Request) -> bool:
    return (
        request.url.scheme == "https"
        or os.getenv("APP_ENV", "development").lower() == "production"
    )


@router.get("/demo-users", response_model=list[DemoUser])
def list_demo_users() -> list[DemoUser]:
    require_demo_auth_enabled()
    return [user.model_copy(deep=True) for user in DEMO_USERS.values()]


@router.post("/demo-login", response_model=DemoUser)
def demo_login(
    payload: DemoLoginRequest,
    request: Request,
    response: Response,
) -> DemoUser:
    require_demo_auth_enabled()
    token = create_session(payload.user_id)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        path="/",
    )
    AuditLog().record(
        request_id=request.state.request_id,
        actor_id=payload.user_id,
        action="auth.login",
        resource_type="session",
        outcome="success",
    )
    return DEMO_USERS[payload.user_id].model_copy(deep=True)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
) -> Response:
    session_token = request.cookies.get(SESSION_COOKIE)
    actor = get_session_user(session_token) if session_token else None
    if session_token is not None:
        delete_session(session_token)
    response.delete_cookie(
        key=SESSION_COOKIE,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        path="/",
    )
    AuditLog().record(
        request_id=request.state.request_id,
        actor_id=actor.user_id if actor else "anonymous",
        action="auth.logout",
        resource_type="session",
        outcome="success",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=DemoUser)
def read_current_user(
    user: DemoUser = Depends(get_current_user),
) -> DemoUser:
    return user
