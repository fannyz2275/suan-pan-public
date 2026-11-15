import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.engine.router import router as engine_router
from app.engine.transfers_router import router as transfers_router
from app.finance.router import router as finance_router
from app.advisor.router import router as advisor_router
from app.plaid.router import router as plaid_router
from app.imports.router import router as imports_router
from app.imports.statements_router import router as statements_router
from app.profile.router import router as profile_router
from app.engine.recurring.router import router as recurring_router
from app.findings.router import router as findings_router
from app.notes.router import router as notes_router
from app.portfolio.router import router as portfolio_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # User AI clients are owned by request/job credential scopes.
    # Start the suan-pan MCP server as a stdio subprocess and keep the client
    # session attached to app.state for the advisor router to reuse.
    app.state.mcp_session = None
    app.state._mcp_stdio_ctx = None
    app.state._mcp_session_ctx = None
    try:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp.server"],
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        stdio_ctx = stdio_client(params)
        read_stream, write_stream = await stdio_ctx.__aenter__()
        session_ctx = ClientSession(read_stream, write_stream)
        session = await session_ctx.__aenter__()
        await session.initialize()
        app.state.mcp_session = session
        app.state._mcp_stdio_ctx = stdio_ctx
        app.state._mcp_session_ctx = session_ctx
        tools_result = await session.list_tools()
        logger.info(
            "MCP server started — %d tools available: %s",
            len(tools_result.tools),
            ", ".join(t.name for t in tools_result.tools),
        )
    except Exception:
        logger.warning(
            "MCP server unavailable — advisor will run without tools",
            exc_info=True,
        )

    # Start the background extraction loop for user-notes capture.
    app.state.notes_stop = asyncio.Event()
    app.state.notes_task = None
    from app.db import get_admin_db
    from app.notes.extraction import run_loop as notes_extract_run_loop
    app.state.notes_task = asyncio.create_task(notes_extract_run_loop(
        db_factory=get_admin_db, gemini=None, stop_event=app.state.notes_stop))

    yield

    if getattr(app.state, "notes_task", None) is not None:
        app.state.notes_stop.set()
        try:
            await asyncio.wait_for(app.state.notes_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            app.state.notes_task.cancel()

    if app.state._mcp_session_ctx is not None:
        try:
            await app.state._mcp_session_ctx.__aexit__(None, None, None)
        except Exception:
            logger.debug("MCP session close failed", exc_info=True)
    if app.state._mcp_stdio_ctx is not None:
        try:
            await app.state._mcp_stdio_ctx.__aexit__(None, None, None)
        except Exception:
            logger.debug("MCP stdio close failed", exc_info=True)


app = FastAPI(title="Suan-Pan API", lifespan=lifespan)
from app.provider_credentials.scope import CredentialScopeMiddleware
from app.provider_credentials.router import router as provider_keys_router
from app.provider_credentials.crypto import CredentialError
app.add_middleware(CredentialScopeMiddleware)
app.include_router(provider_keys_router)

@app.exception_handler(CredentialError)
async def credential_error_handler(request, exc):
    return JSONResponse(status_code=exc.status, content={"detail":str(exc)}, headers={"Cache-Control":"no-store"})


ALLOWED_ORIGINS = {
    settings.frontend_url,
    "http://localhost:5173", "http://localhost:5174",
    "http://127.0.0.1:5173", "http://127.0.0.1:5174",
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Attach CORS headers manually. Starlette's CORSMiddleware doesn't run
    # on responses produced by exception handlers, so without this the
    # browser reports "Network Error" and the real message is hidden.
    origin = request.headers.get("origin")
    headers = {}
    if origin in ALLOWED_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Vary"] = "Origin"
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers=headers,
    )


@app.get("/health")
def health_check():
    return {"status": "ok"}


import os as _os

if _os.environ.get("EVAL_MOCKS") == "1":
    from unittest.mock import AsyncMock as _AsyncMock

    @app.get("/eval/health")
    async def eval_health():
        # Inspect whether each external client has been replaced with a mock.
        # Import lazily so we don't pay the import cost in production.
        import app.portfolio.fred as _fred_module  # type: ignore
        import app.portfolio.statement_parser as _parser_module  # type: ignore
        import app.plaid.router as _plaid_router  # type: ignore

        fred_mocked = getattr(
            _fred_module.fetch_fred_series, "__module__", ""
        ).startswith("unittest")
        gemini_mocked = isinstance(
            _parser_module.parse_investment_statement, _AsyncMock
        )
        # FakePlaidClient is defined in the eval conftest; check by name
        plaid_mocked = type(
            getattr(_plaid_router, "_plaid_client", None)
        ).__name__ == "FakePlaidClient"

        return {
            "eval_mocks": True,
            "fred_mocked": fred_mocked,
            "gemini_mocked": gemini_mocked,
            "plaid_mocked": plaid_mocked,
        }

    @app.get("/eval/tool_calls/{session_id}")
    async def eval_tool_calls(session_id: str):
        from app.eval.context import get_tool_calls
        return get_tool_calls(session_id)

from app.auth.middleware import get_current_user
from fastapi import Depends

@app.get("/me")
async def get_me(user=Depends(get_current_user)):
    return {"user_id": str(user.id), "email": user.email}

app.include_router(finance_router)
app.include_router(engine_router)
app.include_router(transfers_router)
app.include_router(advisor_router)
app.include_router(plaid_router)
app.include_router(imports_router)
app.include_router(statements_router)
app.include_router(profile_router)
app.include_router(recurring_router)
app.include_router(findings_router)
app.include_router(notes_router)
app.include_router(portfolio_router)
from app.policy.router import router as policy_router
app.include_router(policy_router)
