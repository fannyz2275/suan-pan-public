from app.provider_credentials.scope import gemini_client
import asyncio
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from google import genai
from google.genai import types
from pydantic import BaseModel

from app.advisor.context import SYSTEM_PROMPT, build_financial_context
from app.advisor.parser import parse_advisor_actions, strip_actions_block
from app.policy import intent as policy_intent
from app.policy import tool_priors as policy_tool_priors
from app.advisor.validators import (
    check_number_consistency,
    redact_internal_terms,
    redact_pii,
    strip_markdown_tables,
    validate_actions,
)
from app.advisor.resilience import (
    TransientError,
    call_tool_with_timeout,
    classify_gemini_error,
    fallback_message,
    stream_with_retry,
)
from app.auth.middleware import get_current_user
from app.config import settings
from app.db import get_admin_db as _db
from app.eval.context import record_tool_call
from app.engine.recurring.schema import Status as _RecurringStatus
from app.engine.recurring.store import load_rules as _load_recurring_rules
from app.engine.snapshot import compute_snapshot

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/advisor", tags=["advisor"])
from app.advisor.evidence.routes import router as evidence_router
router.include_router(evidence_router)

TOOL_CALL_TIMEOUT = 30.0  # override in tests via monkeypatch
HEARTBEAT_INTERVAL = 15.0  # seconds between SSE keepalive frames during slow tool calls


async def _call_with_heartbeat_and_result(call_fn, name, args):
    """Yields SSE heartbeat lines while waiting; final yield is ('result', <value>).

    Guarantees the underlying task is cancelled if the consumer abandons the
    generator (e.g. client disconnect breaks out of `async for`) to avoid
    orphaned background work.
    """
    task = asyncio.create_task(call_fn(name, args))
    try:
        while True:
            try:
                result = await asyncio.wait_for(asyncio.shield(task), timeout=HEARTBEAT_INTERVAL)
                yield ("result", result)
                return
            except asyncio.TimeoutError:
                if task.done():
                    yield ("result", task.result())
                    return
                yield ("heartbeat", None)
    finally:
        if not task.done():
            task.cancel()


def _gemini():
    from app.advisor.chat_provider import chat_client
    return chat_client()


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


def _to_gemini_messages(history: list) -> list[types.Content]:
    """Convert chat history dicts to Gemini Content objects, appending tool context summaries."""
    result = []
    for m in history:
        role = "model" if m["role"] == "assistant" else "user"
        content = m["content"]
        tc = m.get("tool_context")
        if tc and role == "model":
            parts = []
            for call in tc.get("tool_calls", []):
                parts.append(f"{call['tool']}: {call.get('summary', '')}")
            for mut in tc.get("mutations", []):
                parts.append(f"updated {mut.get('description', mut.get('tool', ''))}")
            if parts:
                content += f"\n[Tool context: {'; '.join(parts)}]"
        result.append(types.Content(role=role, parts=[types.Part(text=content)]))
    return result


def _strip_user_id_from_tools(genai_tools: list) -> list:
    """Remove user_id from the Gemini-facing tool schema — injected by the router."""
    for tool in genai_tools:
        for fd in (tool.function_declarations or []):
            if not fd.parameters:
                continue
            params = fd.parameters
            if hasattr(params, "model_dump"):
                # Pydantic model (google.genai types.Schema)
                props = getattr(params, "properties", None)
                if props is not None and "user_id" in props:
                    del props["user_id"]
                required = getattr(params, "required", None)
                if required and "user_id" in required:
                    params.required = [r for r in required if r != "user_id"]
            elif isinstance(params, dict):
                params.get("properties", {}).pop("user_id", None)
                if "required" in params:
                    params["required"] = [r for r in params["required"] if r != "user_id"]
            else:
                # Fallback: attribute access
                props = getattr(params, "properties", None)
                if props is not None and "user_id" in props:
                    try:
                        del props["user_id"]
                    except Exception:
                        pass
                required = getattr(params, "required", None)
                if required and "user_id" in required:
                    try:
                        params.required = [r for r in required if r != "user_id"]
                    except Exception:
                        pass
            logger.debug(
                "After stripping user_id — tool %s properties: %s",
                getattr(fd, "name", "?"),
                list((getattr(fd.parameters, "properties", None) or {}).keys()),
            )
    return genai_tools


DISPLAYABLE_TABLE_MIN_ROWS = 10


def _build_displayable_table(tool_name: str, result: object, params: dict | None) -> dict | None:
    """When a tool returns a bulky list, return a structured payload the
    frontend renders as an inline expandable card. The model is told
    (via SYSTEM_PROMPT) to summarize in prose and skip enumeration when
    this payload is present.
    """
    try:
        params = params or {}
        if tool_name == "get_transactions" and isinstance(result, list) and len(result) >= DISPLAYABLE_TABLE_MIN_ROWS:
            window = ""
            if params.get("date_from") and params.get("date_to"):
                window = f", {params['date_from']} to {params['date_to']}"
            pat = params.get("description_pattern")
            title = f"Transactions{(' matching ' + repr(pat)) if pat else ''}{window}".strip()
            total = sum(abs(t.get("amount", 0)) for t in result)
            return {
                "title": title,
                "summary": f"{len(result)} transactions · ${total:,.0f} total",
                "columns": [
                    {"key": "date", "label": "Date"},
                    {"key": "description", "label": "Description"},
                    {"key": "category", "label": "Category"},
                    {"key": "amount", "label": "Amount", "align": "right", "format": "currency"},
                ],
                "rows": [
                    {
                        "date": t.get("date"),
                        "description": t.get("description"),
                        "category": t.get("category"),
                        "amount": t.get("amount"),
                    }
                    for t in result
                ],
            }
        if tool_name == "list_recurring_rules" and isinstance(result, list) and len(result) >= DISPLAYABLE_TABLE_MIN_ROWS:
            expense_total = sum(r.get("monthly_equivalent", 0) for r in result if r.get("direction") == "expense")
            income_total = sum(r.get("monthly_equivalent", 0) for r in result if r.get("direction") == "income")
            if income_total > 0 and expense_total > 0:
                summary_str = f"{len(result)} rules · expenses ${expense_total:,.0f}/mo · income ${income_total:,.0f}/mo"
            elif expense_total > 0:
                summary_str = f"{len(result)} rules · ${expense_total:,.0f}/mo expenses"
            else:
                summary_str = f"{len(result)} rules · ${income_total:,.0f}/mo income"
            return {
                "title": "Recurring rules",
                "summary": summary_str,
                "columns": [
                    {"key": "keyword", "label": "Merchant"},
                    {"key": "frequency", "label": "Frequency"},
                    {"key": "monthly_equivalent", "label": "$/mo", "align": "right", "format": "currency"},
                    {"key": "status", "label": "Status"},
                ],
                "rows": result,
            }
        if tool_name == "detect_transfers" and isinstance(result, list) and len(result) >= DISPLAYABLE_TABLE_MIN_ROWS:
            return {
                "title": "Likely account-to-account transfers",
                "summary": f"{len(result)} transfers detected",
                "columns": [
                    {"key": "date", "label": "Date"},
                    {"key": "description", "label": "Description"},
                    {"key": "amount", "label": "Amount", "align": "right", "format": "currency"},
                    {"key": "reason", "label": "Reason"},
                ],
                "rows": [
                    {
                        "date": r.get("date"),
                        "description": r.get("description"),
                        "amount": r.get("amount"),
                        "reason": r.get("reason"),
                    }
                    for r in result
                ],
            }
    except Exception:
        return None
    return None


def _summarize_tool_result(tool_name: str, result: object) -> str:
    try:
        if tool_name == "get_transactions" and isinstance(result, list):
            total = sum(abs(t.get("amount", 0)) for t in result)
            return f"{len(result)} transactions, ${total:,.0f} total"
        if tool_name == "get_spending_by_category" and isinstance(result, list):
            top = result[:3]
            cats = ", ".join(f"{r['category']} (${r['total']:,.0f})" for r in top)
            return f"{len(result)} categories; top: {cats}"
        if tool_name == "detect_transfers" and isinstance(result, list):
            if not result:
                return "no transfers detected"
            top = result[:3]
            descs = "; ".join(f"${abs(t['amount']):,.0f} {t['description'][:25]}" for t in top)
            return f"{len(result)} likely transfers: {descs}"
        if tool_name == "compare_spending_periods" and isinstance(result, dict):
            return f"Period A ${result.get('total_a', 0):,.0f} vs Period B ${result.get('total_b', 0):,.0f} (delta ${result.get('delta', 0):+,.0f})"
        if tool_name == "update_transaction_category" and isinstance(result, dict):
            return f"recategorized '{result.get('description', '')}' from {result.get('old_category')} to {result.get('new_category')}"
        if tool_name == "bulk_recategorize" and isinstance(result, dict):
            mode = result.get("mode", "executed")
            if mode == "preview":
                return f"previewed {len(result.get('matched', []))} matches"
            if mode == "error":
                return f"error: {result.get('error')}"
            return f"recategorized {result.get('updated_count', 0)} transactions; {len(result.get('failed_ids', []))} failed"
        if tool_name == "rescan_transfers" and isinstance(result, dict):
            return f"rescanned — {result.get('paired', 0)} auto-paired, {result.get('orphans', 0)} flagged for review"
    except Exception:
        pass
    return str(result)[:120]


def _get_mcp_session(request: Request):
    return getattr(request.app.state, "mcp_session", None)


def _load_pending_transfer_reviews(db, user_id: str) -> dict:
    """Collect orphaned transfer candidates so the advisor can mention them."""
    from datetime import date, timedelta

    examples = (
        db.table("transactions")
        .select("date,description,amount,account_id")
        .eq("user_id", user_id)
        .eq("transfer_status", "needs_review")
        .order("date", desc=True)
        .limit(3)
        .execute()
        .data
    )
    count_result = (
        db.table("transactions")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("transfer_status", "needs_review")
        .execute()
    )
    count_total = getattr(count_result, "count", None) or 0
    cutoff_90d = (date.today() - timedelta(days=90)).isoformat()
    visible_result = (
        db.table("transactions")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("transfer_status", "needs_review")
        .gte("date", cutoff_90d)
        .execute()
    )
    count_visible = getattr(visible_result, "count", None) or 0

    acct_ids = [e["account_id"] for e in examples if e.get("account_id")]
    acct_name_by_id: dict[str, str] = {}
    if acct_ids:
        acct_rows = (
            db.table("accounts")
            .select("id,name")
            .in_("id", list(set(acct_ids)))
            .execute()
            .data
        )
        acct_name_by_id = {a["id"]: a["name"] for a in acct_rows}

    return {
        "count_total": count_total,
        "count_visible": count_visible,
        "examples": [
            {
                "date": e["date"],
                "description": e["description"],
                "amount": e["amount"],
                "account_name": acct_name_by_id.get(e.get("account_id"), "—"),
            }
            for e in examples
        ],
    }


def _build_pending_recurring_prompts(db, user_id: str) -> list[str]:
    """Short one-liners for each pending_review recurring rule (cap 3)."""
    from uuid import UUID
    rules = _load_recurring_rules(db, UUID(user_id))
    pending = [r for r in rules if r.status == _RecurringStatus.PENDING_REVIEW]
    prompts: list[str] = []
    for r in pending[:3]:
        freq = r.frequency
        direction = r.direction
        seen = r.last_seen_date.isoformat() if r.last_seen_date else "recently"
        prompts.append(
            f"I noticed a possible recurring {direction}: **{r.keyword}**, "
            f"~${r.amount_median:.0f} {freq}. Last seen {seen}. "
            f"Reply *yes*, *no*, or *edit ...*."
        )
    return prompts


def _prior_preview_matches(session_history_tool_calls, live_tool_calls, args) -> bool:
    """Return True if a dry_run=true bulk_recategorize with the same
    description_pattern / date_from / date_to / new_category was already
    executed in this session (either earlier in the current request or in a
    prior message persisted to chat_messages.tool_context)."""
    required = {
        "description_pattern": args.get("description_pattern"),
        "date_from": args.get("date_from"),
        "date_to": args.get("date_to"),
        "new_category": args.get("new_category"),
    }
    # Search newest-first (live tool_calls first, then history reversed)
    for tc in list(reversed(live_tool_calls)) + list(reversed(session_history_tool_calls)):
        if tc.get("tool") != "bulk_recategorize":
            continue
        p = tc.get("params", {}) or {}
        if p.get("dry_run") is not True:
            continue
        if all(p.get(k) == v for k, v in required.items()):
            return True
    return False


def _load_prev_assistant_message(db, session_id: Optional[str]) -> Optional[str]:
    """Fetch the most recent assistant message text for `session_id`.

    Used by the Tier 0 sparse gate's post-question trap: a one-word user
    reply ("yes", "ok") becomes substantive when it answers a question the
    advisor just asked. Returns None when there's no session yet (first
    turn) or the lookup fails (we degrade to "no prev question" which is
    the conservative — substantive — branch).
    """
    if not session_id:
        return None
    try:
        rows = (
            db.table("chat_messages")
            .select("content")
            .eq("session_id", session_id)
            .eq("role", "assistant")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        logger.exception("prev_assistant lookup failed for session=%s", session_id)
        return None
    return rows[0]["content"] if rows else None


async def _build_context_block(
    db, request, *, uid, profile, snapshot, goals, accounts,
    last_user_message, prev_assistant_msg,
    pending_transfer_reviews, recurring_rules,
):
    """Per-turn context block. 100% of users go through the tiered builder
    (Tier 0 sparse gate + Tier 1 identity + Tier 2 live state + Tier 3
    scored retrieval). The legacy builder + per-user flag are gone."""
    return await build_financial_context(
        db,
        gemini_client(optional=True),
        user_id=uid,
        profile=profile,
        snapshot=snapshot,
        goals=goals,
        accounts=accounts,
        last_user_message=last_user_message,
        prev_assistant_msg=prev_assistant_msg,
        pending_transfer_reviews=pending_transfer_reviews,
        recurring_rules=recurring_rules,
    )


@router.post("/chat")
async def chat(body: ChatRequest, request: Request, user=Depends(get_current_user)):
    client_for_request = _gemini()
    uid = str(user.id)
    db = _db()
    # Service-role queries bypass RLS: authorize before ANY session/context access.
    owned_session = None
    if body.session_id:
        rows = (db.table("chat_sessions").select("id,kind,snapshot_summary")
                .eq("id", body.session_id).eq("user_id", uid).execute().data or [])
        if not rows:
            raise HTTPException(status_code=404, detail="Conversation not found")
        owned_session = rows[0]
    mcp_session = _get_mcp_session(request)

    # Load financial context
    profile_rows = db.table("profiles").select("*").eq("id", uid).execute().data
    profile = profile_rows[0] if profile_rows else {}
    accounts = db.table("accounts").select("*").eq("user_id", uid).eq("is_active", True).execute().data
    goals = db.table("goals").select("*").eq("user_id", uid).eq("is_active", True).execute().data

    pending_transfer_reviews = _load_pending_transfer_reviews(db, uid)
    try:
        from uuid import UUID
        recurring_rules = _load_recurring_rules(db, UUID(uid))
    except Exception:
        logger.exception("Failed to load recurring rules")
        recurring_rules = []

    snapshot = compute_snapshot(accounts)
    prev_assistant_msg = _load_prev_assistant_message(db, body.session_id)
    # Classify the user's message once per turn into a ctx_signature label
    # used by the per-user tool-priors layer for both reordering at chat
    # start and tagging tool-call logs.
    ctx_signature = policy_intent.classify(body.message)
    context_block = await _build_context_block(
        db, request,
        uid=uid, profile=profile, snapshot=snapshot, goals=goals,
        accounts=accounts,
        last_user_message=body.message,
        prev_assistant_msg=prev_assistant_msg,
        pending_transfer_reviews=pending_transfer_reviews,
        recurring_rules=recurring_rules,
    )

    # Session
    session_id = body.session_id
    findings_review_prompt: str | None = None
    if not session_id:
        session = db.table("chat_sessions").insert({"user_id": uid}).execute().data[0]
        session_id = session["id"]
    elif owned_session and owned_session.get("kind") == "findings_review":
        findings_review_prompt = owned_session.get("snapshot_summary")

    # History (last 20 messages, include tool_context for replay)
    history = (
        db.table("chat_messages")
        .select("id,role,content,tool_context")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
        .data
    )
    messages = [{"role": m["role"], "content": m["content"], "tool_context": m.get("tool_context")} for m in history[-20:]]
    user_message = f"{context_block}\n\nUser: {body.message}"
    messages.append({"role": "user", "content": user_message})

    # Save user message
    db.table("chat_messages").insert({
        "session_id": session_id,
        "role": "user",
        "content": body.message,
    }).execute()

    full_response = ""

    # Load session-history tool_calls ONCE per request (cheap, small) so the
    # guardrail can check whether a destructive bulk_recategorize was
    # previously previewed in an earlier turn of this session.
    history_tool_calls: list[dict] = []
    try:
        hist_rows = (
            db.table("chat_messages")
            .select("tool_context")
            .eq("session_id", session_id)
            .not_.is_("tool_context", "null")
            .order("created_at")
            .execute()
            .data
        )
        for row in hist_rows or []:
            tc = row.get("tool_context") or {}
            history_tool_calls.extend(tc.get("tool_calls", []))
    except Exception:
        logger.exception("Failed to load session tool_context history")

    async def generate():
        nonlocal full_response
        tool_context: dict = {"tool_calls": [], "mutations": [], "validation_warnings": []}
        tool_outputs_this_turn: list = []
        saved = False

        def _persist_assistant_message():
            display_text = strip_actions_block(full_response)
            tc_to_save = tool_context if (
                tool_context["tool_calls"]
                or tool_context["mutations"]
                or tool_context["validation_warnings"]
            ) else None
            try:
                res = db.table("chat_messages").insert({
                    "session_id": session_id,
                    "role": "assistant",
                    "content": display_text,
                    "tool_context": tc_to_save,
                }).execute()
                return res.data[0]["id"] if res.data else None
            except Exception:
                logger.exception("Failed to persist assistant message")
                return None

        try:
            gemini_client = client_for_request  # scoped until the stream closes
            gemini_messages = _to_gemini_messages(messages)

            # Build Gemini config with optional MCP tools
            system_instruction = SYSTEM_PROMPT
            if findings_review_prompt:
                system_instruction = f"{SYSTEM_PROMPT}\n\n---\n\n{findings_review_prompt}"
            config_kwargs: dict = {
                "system_instruction": system_instruction,
                "max_output_tokens": 4096,
            }

            if mcp_session is not None:
                try:
                    from google.genai._mcp_utils import mcp_to_gemini_tools
                    tools_result = await mcp_session.list_tools()
                    genai_tools = _strip_user_id_from_tools(mcp_to_gemini_tools(tools_result.tools))
                    # Per-user tool ordering: reorder each Tool's function
                    # declarations so this user's most-useful tools for the
                    # current ctx_signature surface first. Best-effort —
                    # falls through to default order on any failure.
                    for t in genai_tools:
                        fds = getattr(t, "function_declarations", None)
                        if fds:
                            t.function_declarations = policy_tool_priors.reorder_tools(
                                db, user_id=uid, ctx_signature=ctx_signature,
                                tools=fds,
                            )
                    config_kwargs["tools"] = genai_tools
                    config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
                except Exception:
                    logger.warning("Failed to load MCP tools — running without tools", exc_info=True)

            config = types.GenerateContentConfig(**config_kwargs)
            contents = list(gemini_messages)

            # Hoisted once: factory takes the current `contents` list so each
            # retry attempt sees the latest conversation turns. Defined outside
            # the while-loop so we don't re-create the closure every iteration.
            async def _open_stream(contents_snapshot):
                try:
                    return await gemini_client.aio.models.generate_content_stream(
                        model="gemini-2.5-flash",
                        contents=contents_snapshot,
                        config=config,
                    )
                except TransientError:
                    raise
                except Exception as e:
                    if classify_gemini_error(e):
                        raise TransientError(str(e)) from e
                    raise

            # Multi-turn tool-call loop
            MAX_TOOL_TURNS = 10
            tool_turns = 0
            stream_errored = False
            while tool_turns < MAX_TOOL_TURNS:
                function_calls_seen = []

                try:
                    stream = await stream_with_retry(
                        lambda: _open_stream(contents), max_attempts=3, backoff=(1.0, 3.0)
                    )
                    async for chunk in stream:
                        if chunk.text:
                            full_response += chunk.text
                            yield f"data: {json.dumps({'text': chunk.text})}\n\n"
                        if chunk.function_calls:
                            function_calls_seen.extend(chunk.function_calls)
                except Exception as e:
                    logger.exception("Gemini stream failed")
                    err_msg = f"\n\n[Error while processing your request: {e}]"
                    full_response += err_msg
                    yield f"data: {json.dumps({'text': err_msg})}\n\n"
                    stream_errored = True
                    break

                if not function_calls_seen or mcp_session is None:
                    break

                # Execute tool calls
                model_fc_parts = []
                tool_response_parts = []

                for fc in function_calls_seen:
                    yield f"data: {json.dumps({'tool_call': fc.name, 'status': 'running'})}\n\n"
                    model_fc_parts.append(types.Part(function_call=fc))

                    # Inject user_id (not visible to Gemini)
                    args = dict(fc.args) if fc.args else {}
                    args["user_id"] = uid

                    # Tool-priors logging — record success/failure + duration
                    # at every outcome path. The closure captures session_id +
                    # uid + ctx_signature so each branch only passes the local
                    # success bool + elapsed time.
                    fc_start = time.perf_counter()
                    def _log(succeeded: bool, *, _name=fc.name, _args=args):
                        elapsed_ms = int((time.perf_counter() - fc_start) * 1000)
                        policy_tool_priors.log_tool_call(
                            db, user_id=uid, session_id=session_id,
                            message_id=None,
                            tool_name=_name, args=_args,
                            ctx_signature=ctx_signature,
                            succeeded=succeeded, duration_ms=elapsed_ms,
                        )

                    # Guardrail: reject destructive bulk_recategorize calls
                    # that were never previewed in this session. Treat
                    # anything other than explicit True as destructive — a
                    # missing dry_run key must not bypass the check.
                    if fc.name == "bulk_recategorize" and (fc.args or {}).get("dry_run") is not True:
                        if not _prior_preview_matches(
                            history_tool_calls,
                            tool_context["tool_calls"],
                            dict(fc.args or {}),
                        ):
                            guard_err = {
                                "error": "destructive_call_not_previewed",
                                "message": "Call bulk_recategorize with dry_run=true first and confirm with the user.",
                            }
                            tool_response_parts.append(
                                types.Part.from_function_response(name=fc.name, response=guard_err)
                            )
                            tool_context["tool_calls"].append({
                                "tool": fc.name,
                                "params": {k: v for k, v in fc.args.items()} if fc.args else {},
                                "summary": "rejected: not previewed",
                            })
                            _log(succeeded=False)
                            yield f"data: {json.dumps({'tool_call': fc.name, 'status': 'done'})}\n\n"
                            # Surface error to the client stream body so tests/UI can see it
                            yield f"data: {json.dumps({'error': guard_err['error'], 'message': guard_err['message']})}\n\n"
                            continue

                    # Safe default: for bulk_recategorize, if the model omits
                    # dry_run entirely, force it to True (preview mode) rather
                    # than relying on MCP's default. This only applies to
                    # bulk_recategorize; other tools are untouched.
                    if fc.name == "bulk_recategorize" and "dry_run" not in args:
                        args["dry_run"] = True

                    try:
                        async def _do_call(n, a):
                            return await mcp_session.call_tool(n, a)

                        gen = _call_with_heartbeat_and_result(
                            lambda n, a: call_tool_with_timeout(
                                _do_call, n, a, timeout=TOOL_CALL_TIMEOUT
                            ),
                            fc.name,
                            args,
                        )
                        result_obj = None
                        async for kind, value in gen:
                            if kind == "heartbeat":
                                yield ": keepalive\n\n"
                            elif kind == "result":
                                result_obj = value
                                break

                        if isinstance(result_obj, dict) and result_obj.get("error") == "tool_timeout":
                            # Synthesize function response with the timeout error payload
                            tool_response_parts.append(
                                types.Part.from_function_response(name=fc.name, response=result_obj)
                            )
                            tool_context["tool_calls"].append({
                                "tool": fc.name,
                                "params": {k: v for k, v in fc.args.items()} if fc.args else {},
                                "summary": f"timed out after {TOOL_CALL_TIMEOUT}s",
                            })
                            _log(succeeded=False)
                            yield f"data: {json.dumps({'tool_call': fc.name, 'status': 'done'})}\n\n"
                            continue

                        mcp_result = result_obj

                        # Parse result for summarization
                        result_data: object = None
                        if mcp_result.content:
                            try:
                                result_data = json.loads(mcp_result.content[0].text)
                            except Exception:
                                result_data = mcp_result.content[0].text

                        # Accumulate for the number-consistency validator
                        tool_outputs_this_turn.append(result_data)

                        # Eval-mode capture: no-op in production
                        record_tool_call(session_id, fc.name, args, result_data)

                        # Emit structured tool_result for the frontend to render
                        # a confirm card (bulk_recategorize only for now).
                        if fc.name == "bulk_recategorize" and isinstance(result_data, dict):
                            yield f"data: {json.dumps({'tool_result': {'tool': fc.name, **result_data}})}\n\n"

                        # Emit attribution payload so the frontend can render
                        # AttributionChips above the prose for portfolio attribution turns.
                        if fc.name == "portfolio_get_attribution" and isinstance(result_data, dict) and "start_value" in result_data:
                            yield f"data: {json.dumps({'attribution_result': result_data})}\n\n"

                        # Record tool context
                        params_dict = {k: v for k, v in fc.args.items()} if fc.args else {}
                        call_record = {
                            "tool": fc.name,
                            "params": params_dict,
                            "summary": _summarize_tool_result(fc.name, result_data),
                        }
                        # Inline expandable table card — see /tmp/suan-pan-table-sketch.html
                        # for the visual spec. Attached to the persisted tool_call
                        # so reload-and-scroll-back keeps the card visible.
                        table = _build_displayable_table(fc.name, result_data, params_dict)
                        if table is not None:
                            call_record["displayable_table"] = table
                            yield f"data: {json.dumps({'displayable_table': {'tool': fc.name, **table}})}\n\n"
                        tool_context["tool_calls"].append(call_record)

                        # Track mutations separately
                        if fc.name in ("update_transaction_category", "bulk_recategorize") and isinstance(result_data, dict):
                            tool_context["mutations"].append({"tool": fc.name, **result_data})

                        func_response = types.FunctionResponse.from_mcp_response(
                            name=fc.name, response=mcp_result
                        )
                        tool_response_parts.append(types.Part(function_response=func_response))
                        # Tool-priors signal: a result that's a dict with an
                        # "error" key counts as a miss; everything else is a
                        # success. The advisor doesn't always distinguish —
                        # this proxy is good enough for the per-user reorder.
                        succeeded = not (
                            isinstance(result_data, dict) and "error" in result_data
                        )
                        _log(succeeded=succeeded)

                    except Exception as e:
                        logger.exception("Tool call %s failed", fc.name)
                        tool_response_parts.append(
                            types.Part.from_function_response(
                                name=fc.name,
                                response={"error": str(e)},
                            )
                        )
                        tool_context["tool_calls"].append({
                            "tool": fc.name,
                            "params": {k: v for k, v in fc.args.items()} if fc.args else {},
                            "summary": f"error: {str(e)[:80]}",
                        })
                        _log(succeeded=False)

                    yield f"data: {json.dumps({'tool_call': fc.name, 'status': 'done'})}\n\n"

                # Append model FC turn and tool results to conversation
                contents.append(types.Content(role="model", parts=model_fc_parts))
                contents.append(types.Content(role="user", parts=tool_response_parts))
                tool_turns += 1
                # Reset draft: pre-tool-call commentary from this iteration
                # was already streamed; the next iteration's text is the
                # real answer. Frontend resets accumulator on this marker
                # so users see only the post-tool-call response.
                full_response = ""
                yield f"data: {json.dumps({'replace_text': True})}\n\n"

            # Empty-stream recovery: when Gemini returns zero tokens and the
            # previous assistant turn ended with a question, the user's short
            # reply is almost certainly a direct answer to that question. Retry
            # once with a synthesized continuation turn that restates the prior
            # question so Gemini has enough context to proceed rather than going
            # silent. This covers the "50 years (600 months)" follow-up case.
            if not stream_errored and not full_response.strip():
                _prev = prev_assistant_msg or ""
                if _prev.rstrip().endswith("?") and body.session_id:
                    logger.warning(
                        "empty_stream on follow-up answer — retrying with prior-question context",
                        extra={
                            "cause": "empty_stream_followup_retry",
                            "session_message_count": len(messages),
                            "last_user_message_len": len(body.message),
                        },
                    )
                    # Build a synthesized user turn that restates the Q+A pair
                    # so Gemini sees it as a self-contained request rather than
                    # a dangling short reply. Use the last 300 chars of the
                    # prior message to stay within a tight token budget.
                    prior_q = _prev.strip()[-300:].strip()
                    retry_text = (
                        f"{context_block}\n\n"
                        f"User (continuing from your previous question \"{prior_q}\"): "
                        f"{body.message}"
                    )
                    retry_contents = list(gemini_messages[:-1]) + [
                        types.Content(role="user", parts=[types.Part(text=retry_text)])
                    ]
                    try:
                        retry_stream = await stream_with_retry(
                            lambda: _open_stream(retry_contents), max_attempts=2, backoff=(1.0,)
                        )
                        async for chunk in retry_stream:
                            if chunk.text:
                                full_response += chunk.text
                                yield f"data: {json.dumps({'text': chunk.text})}\n\n"
                    except Exception:
                        logger.exception("Follow-up retry stream failed")

            # Fallback when empty response or max turns reached. Skip if the
            # stream already errored — we've already emitted an error note and
            # shouldn't overwrite it with a generic "please rephrase" message.
            if not stream_errored:
                fb = fallback_message(
                    full_response=full_response,
                    tool_turns=tool_turns,
                    max_turns=MAX_TOOL_TURNS,
                    session_message_count=len(messages),
                    last_user_message_len=len(body.message),
                )
                if fb is not None:
                    full_response = fb
                    yield f"data: {json.dumps({'text': fb})}\n\n"

            # In-flight validators: number-consistency + PII redaction.
            # PII redaction modifies full_response in place so what gets
            # persisted (and fed through strip_actions_block) has no raw PII.
            num_warnings = check_number_consistency(full_response, tool_outputs_this_turn)
            for w in num_warnings:
                tool_context.setdefault("validation_warnings", []).append(w)

            redacted, pii_warnings = redact_pii(full_response)
            if pii_warnings:
                full_response = redacted
                for w in pii_warnings:
                    tool_context.setdefault("validation_warnings", []).append(w)
                # Emit the redacted text on the wire so downstream consumers
                # (and the end-to-end response body) see "[REDACTED]" rather
                # than the raw sensitive tokens that may have already streamed.
                yield f"data: {json.dumps({'pii_redacted': True, 'redacted_text': redacted})}\n\n"

            # Parse advisor-generated goals and action items BEFORE the
            # internal-term redactor runs — the redactor rewrites action
            # keys like `new_goals` → `goal-create`, which would mangle
            # the JSON inside <actions>...</actions> and silently drop
            # every chat-driven goal-create. Persist from the unredacted
            # source; the user-facing display text is redacted below.
            raw_actions = parse_advisor_actions(full_response)
            valid_actions, action_warnings = validate_actions(raw_actions)
            for w in action_warnings:
                tool_context.setdefault("validation_warnings", []).append(w)
            # Dup-detection pre-flight: if the proposed new goal name is
            # similar to an existing active goal (>=0.6 token-ratio), reject
            # the create and emit a `goal_dedup_blocked` warning. The
            # SYSTEM_PROMPT instructs the model to call update_goal in that
            # case; this guard catches the times it forgets.
            from app.mcp.tools import find_similar_goal as _find_similar
            for goal_data in valid_actions.get("new_goals", []):
                similar = _find_similar(db, uid, candidate_name=goal_data.get("name", ""))
                if similar.get("score", 0) >= 0.6 and similar.get("match"):
                    tool_context.setdefault("validation_warnings", []).append({
                        "type": "goal_dedup_blocked",
                        "candidate": goal_data.get("name"),
                        "match_name": similar["match"].get("name"),
                        "score": similar["score"],
                    })
                    continue
                goal_data["user_id"] = uid
                db.table("goals").insert(goal_data).execute()

            internal_redacted, internal_warnings = redact_internal_terms(full_response)
            if internal_warnings:
                full_response = internal_redacted
                for w in internal_warnings:
                    tool_context.setdefault("validation_warnings", []).append(w)
                yield f"data: {json.dumps({'internal_redacted': True, 'redacted_text': internal_redacted})}\n\n"

            # If any tool call this turn promoted a result to an inline
            # `displayable_table` card, strip pipe-style markdown tables from
            # the bubble so the user doesn't see the same data rendered twice.
            # The model is told (in SYSTEM_PROMPT) not to enumerate; this is
            # belt-and-suspenders for when it does anyway.
            if any("displayable_table" in tc for tc in tool_context["tool_calls"]):
                stripped, stripped_count = strip_markdown_tables(full_response)
                if stripped_count > 0:
                    full_response = stripped
                    tool_context.setdefault("validation_warnings", []).append({
                        "type": "duplicate_table_stripped",
                        "count": stripped_count,
                    })
                    yield f"data: {json.dumps({'table_stripped': True, 'redacted_text': stripped})}\n\n"

            # Save assistant message before emitting the final `done` event so
            # late client aborts still see the persisted row.
            asst_message_id = _persist_assistant_message()
            saved = True

            # PR #4 removed the rolling-summary trigger: notes/extraction.py
            # (the 5-min idle background loop) is now the sole consolidator
            # of chat history into durable memory. The summarizer + the
            # MEMORY_THRESHOLD heuristic + the message_count_at_last_summary
            # column all went away with the legacy advisor/memory.py.

            try:
                for prompt_text in _build_pending_recurring_prompts(db, uid):
                    payload = json.dumps({"text": "\n\n" + prompt_text})
                    yield f"data: {payload}\n\n"
            except Exception:
                logger.exception("Failed to build pending recurring prompts")

            yield f"data: {json.dumps({'session_id': session_id, 'message_id': asst_message_id, 'done': True})}\n\n"
        finally:
            if not saved:
                tool_context["validation_warnings"].append({"type": "client_disconnect"})
                _persist_assistant_message()

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/findings/start")
async def start_findings_session(user=Depends(get_current_user)):
    from fastapi import Response

    from app.advisor.findings_prompt import render_findings_prompt
    from app.findings.router import _load_pending

    findings = _load_pending(str(user.id))
    if not findings:
        return Response(status_code=204)
    db = _db()
    session = (
        db.table("chat_sessions")
        .insert(
            {
                "user_id": str(user.id),
                "title": f"Review {len(findings)} findings",
                "kind": "findings_review",
                "snapshot_summary": render_findings_prompt(findings),
            }
        )
        .execute()
        .data[0]
    )
    return {"session_id": session["id"], "count": len(findings)}


@router.get("/sessions")
async def list_sessions(user=Depends(get_current_user)):
    return _db().table("chat_sessions").select("*").eq("user_id", str(user.id)).order("created_at", desc=True).execute().data


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str, user=Depends(get_current_user)):
    # Verify session belongs to requesting user
    owned = _db().table("chat_sessions").select("id").eq("id", session_id).eq("user_id", str(user.id)).execute().data
    if not owned:
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    return (
        _db().table("chat_messages")
        .select("role,content,tool_context")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
        .data
    )
