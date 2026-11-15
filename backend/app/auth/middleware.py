import logging
import os
from functools import lru_cache
from types import SimpleNamespace

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client

from app.config import settings
from app.provider_credentials.scope import bind_user

bearer_scheme = HTTPBearer(auto_error=False)
log = logging.getLogger(__name__)

EVAL_MOCKS_ENABLED = os.getenv("EVAL_MOCKS") == "1"

if EVAL_MOCKS_ENABLED:
    log.warning(
        "EVAL_MOCKS=1 detected at startup — auth bypass via X-Eval-User-Id is ACTIVE. "
        "This MUST NOT appear in production logs. If you see this in prod, unset "
        "EVAL_MOCKS immediately."
    )


@lru_cache(maxsize=1)
def _supabase_client():
    return create_client(settings.supabase_url, settings.supabase_service_key)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
):
    if EVAL_MOCKS_ENABLED:
        eval_user_id = request.headers.get("X-Eval-User-Id")
        if eval_user_id:
            log.warning("eval-mode auth bypass active for user %s", eval_user_id)
            bind_user(eval_user_id)
            return SimpleNamespace(
                id=eval_user_id,
                email=f"{eval_user_id}@suan-pan.eval",
            )
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        user = _supabase_client().auth.get_user(credentials.credentials)
        bind_user(user.user.id)
        return user.user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
