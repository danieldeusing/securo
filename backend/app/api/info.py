"""Public capability/feature-flag endpoint.

Tells the frontend which optional features are enabled so it can hide
nav items, routes, etc. Lightweight — no auth required.
"""
import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_jwt_strategy, get_user_manager, UserManager
from app.core.config import get_settings
from app.core.database import get_async_session
from app.models.user import User

router = APIRouter(prefix="/api", tags=["info"])


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


@router.get("/info")
async def get_app_info():
    return {
        "features": {
            "agents": _flag("AGENTS_ENABLED"),
            "demo": _flag("DEMO_MODE"),
            "tesouro_direto": _flag("TESOURO_DIRETO_ENABLED"),
        },
    }


@router.post("/auth/demo-login")
async def demo_login(
    session: AsyncSession = Depends(get_async_session),
    user_manager: UserManager = Depends(get_user_manager),
):
    """Mint a JWT for the seeded demo user.

    Only available when DEMO_MODE is on. Lets the public demo frontend
    skip the login form entirely so first-time visitors land directly on
    the dashboard.
    """
    if not get_settings().demo_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    user = await session.scalar(select(User).where(User.email == "demo@securo.app"))
    if user is None:
        # Seed hasn't run yet — surface a clear error so the operator
        # knows to invoke reset_demo.sh / seed_demo.py.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Demo user not seeded yet",
        )

    strategy = get_jwt_strategy()
    token = await strategy.write_token(user)
    return {"access_token": token, "token_type": "bearer"}
