"""Unified statement-import router.

Every upload is scoped to a single (user-picked) account. The router dispatches
parse + write paths by the account's `type`:

- brokerage/retirement -> portfolio statement parser + snapshot writer
- everything else        -> bank-style parser + balance update + transaction inserts

Each row is processed independently. Per-row errors do not abort the whole
call. After all writes land, a transfer rescan runs once and the count of
newly-flagged candidates is returned so the frontend can prompt the user.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.auth.middleware import get_current_user
from app.db import get_admin_db
from app.engine.transfers import scan_transfers_for_user
from app.finance.balance_history import cache_patch, record_history
from app.imports.parser import (
    extract_csv_text,
    extract_pdf_text,
    parse_accounts_from_text,
    parse_transactions_from_text,
)
from app.portfolio import snapshots
from app.portfolio.statement_parser import parse_investment_statement
from app.imports.sections import DetectionError, detect_sections, suggest_account

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/import/statements", tags=["import"])

_SUPPORTED_EXTENSIONS = {".pdf", ".csv", ".txt"}
_MAX_FILE_MB = 10
_MAX_ROWS = 10
_MAX_FILES_PER_ROW = 5
_INVESTMENT_TYPES = {"brokerage", "retirement"}


# ---------- Pydantic models ----------


class RowRef(BaseModel):
    row_id: str
    account_id: str


class BankPreviewBody(BaseModel):
    statement_date: Optional[str] = None
    balance: Optional[float] = None
    transactions: list[dict]


class InvestmentPreviewBody(BaseModel):
    statement_date: str
    cash_value: float
    holdings: list[dict]
    investment_transactions: list[dict]
    total_value_reported: Optional[float] = None
    account_hint: Optional[str] = None
    reported_cash_value: Optional[float] = None
    cash_in_holdings: float = 0


class PreviewGroup(BaseModel):
    row_id: str
    account_id: str
    account_name: str
    account_type: str
    kind: Literal["bank", "investment"]
    error: Optional[str] = None
    preview: Optional[dict] = None
    detected_last4: Optional[str] = None
    source_file: Optional[str] = None
    source_ranges: Optional[list[list[int]]] = None
    error_code: Optional[str] = None
    document_notices: list[dict] = []


class PreviewResponse(BaseModel):
    groups: list[PreviewGroup]


class BankConfirmGroup(BaseModel):
    row_id: str
    account_id: str
    kind: Literal["bank"]
    balance: Optional[float] = None
    statement_date: Optional[str] = None
    transactions: list[dict]


class InvestmentConfirmGroup(BaseModel):
    row_id: str
    account_id: str
    kind: Literal["investment"]
    statement_date: str
    cash_value: float
    holdings: list[dict]
    investment_transactions: list[dict]


class ConfirmRequest(BaseModel):
    groups: list[dict]  # discriminated by kind at runtime


class SavedRow(BaseModel):
    row_id: str
    account_id: str
    error: Optional[str] = None
    # bank-shape
    transactions_created: Optional[int] = None
    transactions_skipped: Optional[int] = None
    balance_updated: Optional[bool] = None
    # investment-shape
    snapshot_id: Optional[str] = None
    holdings_count: Optional[int] = None
    txns_count: Optional[int] = None


class ConfirmResponse(BaseModel):
    ok: bool
    saved: list[SavedRow]
    transfer_candidates_added: int


# ---------- Helpers ----------


def _load_account(db, user_id: str, account_id: str) -> dict:
    rows = (
        db.table("accounts")
        .select("id,name,type,balance,balance_updated_at,created_at,account_number_last4")
        .eq("id", account_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(404, f"account {account_id} not found")
    return rows[0]


def _extract_text(filename: str, body: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        return extract_pdf_text(body)
    if name.endswith(".csv"):
        return extract_csv_text(body)
    if name.endswith(".txt"):
        return body.decode("utf-8", errors="replace")
    raise HTTPException(415, f"{filename}: only PDF, CSV, or TXT supported")


def _validate_file(file: UploadFile, body: bytes) -> None:
    name = (file.filename or "").lower()
    if not any(name.endswith(e) for e in _SUPPORTED_EXTENSIONS):
        raise HTTPException(415, f"{file.filename or '?'}: only PDF, CSV, or TXT supported")
    if len(body) > _MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"{file.filename or '?'}: file too large (max {_MAX_FILE_MB} MB)")


def _bank_preview(text: str, account: dict, *, strict: bool = False) -> BankPreviewBody:
    parsed_accounts = parse_accounts_from_text(text)
    identifiers = {a.get("account_number_last4") for a in parsed_accounts if a.get("account_number_last4")}
    if len(identifiers) > 1 or (account.get("account_number_last4") and identifiers and identifiers != {account["account_number_last4"]}):
        raise ValueError("Account identifiers conflict. Choose the matching account or enable multiple-account mode.")
    parsed_txns = parse_transactions_from_text(text)
    if not parsed_accounts and not parsed_txns:
        raise ValueError("No accounts or transactions found in the statement.")
    if strict and len(parsed_accounts) > 1:
        raise ValueError("Multiple balances remain in one detected section.")
    if strict and parsed_accounts:
        parsed = parsed_accounts[0]
        if parsed.get("type") != account["type"]:
            raise ValueError("Account type disagrees with detected section.")
        if account.get("last4") and parsed.get("account_number_last4") not in (None, account["last4"]):
            raise ValueError("Account identifiers disagree.")
        if account["type"] == "debt" and parsed.get("balance", 0) > 0:
            raise ValueError("Debt balance sign needs review.")

    # Pick the latest-dated parsed account row as the balance source. The
    # parser may emit several account-like rows for one file; we trust the
    # latest statement_date. Fall back to existing DB balance when the
    # parser was empty.
    chosen_acct: Optional[dict] = None
    for a in parsed_accounts:
        if chosen_acct is None or (a.get("statement_date") or "") > (chosen_acct.get("statement_date") or ""):
            chosen_acct = a

    balance = chosen_acct.get("balance") if chosen_acct else account.get("balance")
    statement_date = chosen_acct.get("statement_date") if chosen_acct else None

    return BankPreviewBody(
        statement_date=statement_date,
        balance=balance,
        transactions=parsed_txns,
    )


def _investment_preview(text: str, *, strict: bool = False) -> InvestmentPreviewBody:
    parsed = parse_investment_statement(text)
    if strict and not parsed.get("statement_date"):
        raise ValueError("Investment statement date is missing.")
    sd = parsed.get("statement_date") or date.today().isoformat()
    return InvestmentPreviewBody(
        statement_date=sd,
        cash_value=float(parsed.get("cash_value") or 0),
        holdings=list(parsed.get("holdings", [])),
        investment_transactions=list(parsed.get("investment_transactions", [])),
        total_value_reported=parsed.get("total_value_reported"),
        account_hint=parsed.get("account_hint"),
        reported_cash_value=parsed.get("reported_cash_value"),
        cash_in_holdings=parsed.get("cash_in_holdings", 0),
    )


def _portfolio_total(cash_value: float, holdings: list[dict]) -> float:
    total = float(cash_value or 0)
    for h in holdings:
        mv = h.get("market_value")
        if mv is None:
            mv = float(h.get("quantity") or 0) * float(h.get("price") or 0)
        total += float(mv)
    return total


def _count_new_review_candidates(db, user_id: str) -> int:
    """Count transactions currently in needs_review for this user.

    The scan classifies post-import; the resulting `needs_review` count is
    a proxy for "new candidates the user should look at." A more precise
    diff would require snapshotting pre-scan state — overkill for the UX.
    """
    rows = (
        db.table("transactions")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("transfer_status", "needs_review")
        .execute()
    )
    return int(getattr(rows, "count", None) or len(rows.data or []))


# ---------- Endpoints ----------


def _check_account_identifiers(text: str, account: dict) -> None:
    # Only explicit account labels, not card numbers, dates, or monetary totals.
    matches = re.findall(r"\baccount\s*(?:number|no\.?|ending(?:\s+in)?|#)\s*[:#]?\s*([*xX\d-]*\d{4,})", text, re.IGNORECASE)
    last4s = {re.sub(r"\D", "", value)[-4:] for value in matches}
    full_numbers = {re.sub(r"\D", "", value) for value in matches if '*' not in value and 'x' not in value.lower() and len(re.sub(r"\D", "", value)) > 4}
    if len(last4s) > 1 or len(full_numbers) > 1 or (account.get('account_number_last4') and last4s and last4s != {account['account_number_last4']}):
        raise ValueError("Account identifiers conflict. Choose the matching account or enable multiple-account mode.")


@router.post("/detect", response_model=PreviewResponse)
async def detect_statements(request: Request, user=Depends(get_current_user)):
    form = await request.form()
    files = [f for f in form.getlist("files") if isinstance(f, StarletteUploadFile)]
    if not 1 <= len(files) <= _MAX_FILES_PER_ROW:
        raise HTTPException(400, "Upload between 1 and 5 files.")
    db = get_admin_db()
    accounts = db.table("accounts").select("id,name,type,account_number_last4").eq("user_id", str(user.id)).execute().data or []
    groups = []
    for file_index, file in enumerate(files):
        body = await file.read(_MAX_FILE_MB * 1024 * 1024 + 1)
        _validate_file(file, body)
        try:
            try:
                text = await run_in_threadpool(_extract_text, file.filename or "", body)
            except Exception:
                raise DetectionError("file_read", "Could not read this file. It may be damaged or password-protected.") from None
            sections = await run_in_threadpool(detect_sections, text)
            for section_index, section in enumerate(sections):
                if len(groups) >= _MAX_ROWS:
                    raise DetectionError("section_limit", "Remaining sections exceed the 10-section limit. Upload them separately.")
                kind = "investment" if section["type"] in _INVESTMENT_TYPES else "bank"
                group = PreviewGroup(
                    row_id=f"file-{file_index}-section-{section_index}",
                    account_id="" if section.get("error") else suggest_account(section, accounts),
                    account_name=section["institution"] or "Unidentified institution",
                    account_type=section["type"], kind=kind,
                    detected_last4=section["last4"], source_file=file.filename,
                    source_ranges=section["ranges"], error=section.get("error"),
                    error_code=section.get("error_code"), document_notices=section.get("document_notices", []),
                )
                if not group.error:
                    try:
                        if kind == "investment":
                            preview = await run_in_threadpool(_investment_preview, section["text"], strict=True)
                            preview.account_hint = None
                        else:
                            preview = await run_in_threadpool(_bank_preview, section["text"], {**section, "balance": None}, strict=True)
                        group.preview = preview.model_dump()
                    except (ValueError, TypeError, KeyError):
                        group.error_code = "section_parse"
                        group.error = "Account detected, but its balances or transactions could not be validated. Retry with an account-specific file."
                    except Exception:
                        group.error_code = "provider_unavailable"
                        group.error = "AI service unavailable while parsing this account. Check provider access or billing, then retry."
                groups.append(group)
        except Exception as exc:
            groups.append(PreviewGroup(
                row_id=f"file-{file_index}-error", account_id="", account_name="File needs review",
                account_type="unknown", kind="bank", source_file=file.filename,
                error_code=exc.code if isinstance(exc, DetectionError) else "boundaries",
                error=str(exc) if isinstance(exc, DetectionError) else "Account boundaries could not be validated. Try an account-specific file.",
            ))
    return PreviewResponse(groups=groups)


@router.post("/preview", response_model=PreviewResponse)
async def preview_statements(
    request: Request,
    user=Depends(get_current_user),
):
    form = await request.form()
    rows = form.get("rows")
    if not isinstance(rows, str):
        raise HTTPException(400, "rows form field is required")
    try:
        row_refs = [RowRef(**r) for r in json.loads(rows)]
    except Exception as e:
        raise HTTPException(400, f"rows must be valid JSON: {e}")

    if not row_refs:
        raise HTTPException(400, "at least one row is required")
    if len(row_refs) > _MAX_ROWS:
        raise HTTPException(400, f"too many rows (max {_MAX_ROWS})")
    db = get_admin_db()
    uid = str(user.id)
    groups: list[PreviewGroup] = []

    for ref in row_refs:
        try:
            account = _load_account(db, uid, ref.account_id)
        except HTTPException as exc:
            groups.append(PreviewGroup(
                row_id=ref.row_id, account_id=ref.account_id,
                account_name="(unknown)", account_type="(unknown)",
                kind="bank", error=exc.detail if isinstance(exc.detail, str) else "account not found",
            ))
            continue

        # Files for this row are uploaded under form-field name = row_id.
        raw = form.getlist(ref.row_id)
        files = [f for f in raw if isinstance(f, StarletteUploadFile)]
        if not files:
            groups.append(PreviewGroup(
                row_id=ref.row_id, account_id=ref.account_id,
                account_name=account["name"], account_type=account["type"],
                kind="investment" if account["type"] in _INVESTMENT_TYPES else "bank",
                error="No file provided for this row.",
            ))
            continue
        if len(files) > _MAX_FILES_PER_ROW:
            groups.append(PreviewGroup(
                row_id=ref.row_id, account_id=ref.account_id,
                account_name=account["name"], account_type=account["type"],
                kind="investment" if account["type"] in _INVESTMENT_TYPES else "bank",
                error=f"Too many files for this row (max {_MAX_FILES_PER_ROW}).",
            ))
            continue

        try:
            chunks: list[str] = []
            for f in files:
                body = await f.read()
                _validate_file(f, body)
                chunks.append(_extract_text(f.filename or "", body))
            text = "\n\n".join(c for c in chunks if c.strip())
            if not text.strip():
                raise ValueError("No text could be extracted from the file(s).")
            _check_account_identifiers(text, account)

            kind: Literal["bank", "investment"] = (
                "investment" if account["type"] in _INVESTMENT_TYPES else "bank"
            )
            if kind == "investment":
                body_obj = await run_in_threadpool(_investment_preview, text)
            else:
                body_obj = await run_in_threadpool(_bank_preview, text, account)

            groups.append(PreviewGroup(
                row_id=ref.row_id, account_id=ref.account_id,
                account_name=account["name"], account_type=account["type"],
                kind=kind, error=None, preview=body_obj.model_dump(),
            ))
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("preview row %s failed", ref.row_id)
            groups.append(PreviewGroup(
                row_id=ref.row_id, account_id=ref.account_id,
                account_name=account["name"], account_type=account["type"],
                kind="investment" if account["type"] in _INVESTMENT_TYPES else "bank",
                error=str(e) or "Failed to parse.",
            ))

    return PreviewResponse(groups=groups)


@router.post("/confirm", response_model=ConfirmResponse)
async def confirm_statements(body: ConfirmRequest, user=Depends(get_current_user)):
    if not body.groups:
        raise HTTPException(400, "at least one group is required")
    if len(body.groups) > _MAX_ROWS:
        raise HTTPException(400, f"too many groups (max {_MAX_ROWS})")

    db = get_admin_db()
    uid = str(user.id)
    saved: list[SavedRow] = []

    for g in body.groups:
        row_id = str(g.get("row_id") or "")
        account_id = str(g.get("account_id") or "")
        kind = g.get("kind")

        try:
            account = _load_account(db, uid, account_id)
            if g.get("detected_type") is not None:
                if g.get("destination_confirmed") is not True:
                    raise ValueError("Account destination must be confirmed.")
                if g["detected_type"] != account["type"]:
                    raise ValueError("Destination account type does not match the detected section.")
            if kind == "investment":
                if account["type"] not in _INVESTMENT_TYPES:
                    raise ValueError(
                        f"account type {account['type']} is not investment-capable"
                    )
                group_obj = InvestmentConfirmGroup(**g)
                row = snapshots.create_statement_snapshot(
                    db,
                    user_id=uid,
                    account_id=account_id,
                    snapshot_date=date.fromisoformat(group_obj.statement_date),
                    cash_value=group_obj.cash_value,
                    holdings=group_obj.holdings,
                    investment_transactions=group_obj.investment_transactions,
                )
                # Mirror the snapshot total onto accounts.balance so the
                # net-worth tree, snapshot KPIs, and Accounts breakdown
                # reflect the imported portfolio. Without this the brokerage
                # node sums to zero even though the snapshot rows exist.
                new_balance = _portfolio_total(group_obj.cash_value, group_obj.holdings)
                update_payload: dict[str, Any] = {"balance": new_balance}
                update_payload.update(cache_patch(account, new_balance))
                db.table("accounts").update(update_payload).eq("id", account_id).execute()
                cur_balance = account.get("balance")
                if cur_balance is None or float(cur_balance) != new_balance:
                    record_history(
                        db, account_id=account_id, user_id=uid,
                        balance=new_balance, source="file_import",
                    )
                saved.append(SavedRow(
                    row_id=row_id, account_id=account_id,
                    snapshot_id=row["id"],
                    holdings_count=len(group_obj.holdings),
                    txns_count=len(group_obj.investment_transactions),
                ))
            elif kind == "bank":
                if account["type"] in _INVESTMENT_TYPES:
                    raise ValueError(
                        f"account type {account['type']} requires a portfolio statement"
                    )
                group_obj = BankConfirmGroup(**g)
                balance_updated = _write_bank_group(db, uid, account, group_obj)
                created, skipped = _insert_bank_transactions(db, uid, account_id, group_obj.transactions)
                saved.append(SavedRow(
                    row_id=row_id, account_id=account_id,
                    transactions_created=created,
                    transactions_skipped=skipped,
                    balance_updated=balance_updated,
                ))
            else:
                raise ValueError(f"unknown kind: {kind!r}")
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("confirm row %s failed", row_id)
            saved.append(SavedRow(row_id=row_id, account_id=account_id, error=str(e) or "Failed to save."))

    # Run transfer rescan once, count newly-flagged candidates.
    transfer_candidates_added = 0
    try:
        scan_transfers_for_user(db, user_id=uid)
        transfer_candidates_added = _count_new_review_candidates(db, uid)
    except Exception:
        logger.exception("transfer scan failed for user %s", uid)

    return ConfirmResponse(
        ok=True,
        saved=saved,
        transfer_candidates_added=transfer_candidates_added,
    )


# ---------- Bank-write helpers ----------


def _write_bank_group(db, user_id: str, account: dict, group: BankConfirmGroup) -> bool:
    if group.balance is None:
        return False
    new_balance = float(group.balance)
    cur_balance = account.get("balance")
    update_payload: dict[str, Any] = {"balance": new_balance}
    update_payload.update(cache_patch(account, new_balance))
    db.table("accounts").update(update_payload).eq("id", account["id"]).execute()
    if cur_balance is None or float(cur_balance) != new_balance:
        record_history(
            db, account_id=account["id"], user_id=user_id,
            balance=new_balance, source="file_import",
        )
        return True
    # Same value re-saved still bumps balance_updated_at; not "changed" though.
    return False


def _insert_bank_transactions(
    db, user_id: str, account_id: str, transactions: list[dict],
) -> tuple[int, int]:
    created = 0
    skipped = 0
    for txn in transactions:
        date_s = str(txn.get("date") or "")
        amount = float(txn.get("amount") or 0)
        description = str(txn.get("description") or "")
        category = txn.get("category")

        if not date_s or not description:
            skipped += 1
            continue

        existing = (
            db.table("transactions")
            .select("id")
            .eq("user_id", user_id)
            .eq("source", "manual")
            .eq("account_id", account_id)
            .eq("date", date_s)
            .eq("amount", amount)
            .eq("description", description)
            .limit(1)
            .execute()
            .data
        )
        if existing:
            skipped += 1
            continue

        db.table("transactions").insert({
            "user_id": user_id,
            "account_id": account_id,
            "date": date_s,
            "description": description,
            "amount": amount,
            "category": category,
            "source": "manual",
        }).execute()
        created += 1

    return created, skipped
