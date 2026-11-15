import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.auth.middleware import get_current_user
from app.db import get_admin_db as _db
from app.engine.transfers import safe_scan_transfers_for_user
from app.finance.balance_history import cache_patch, record_history
from app.imports.parser import (
    parse_accounts_from_text,
    parse_transactions_from_text,
    extract_pdf_text,
    extract_csv_text,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/import", tags=["import"])


_SUPPORTED_EXTENSIONS = {".pdf", ".csv", ".txt"}
_MAX_FILE_MB = 10


class ParsedAccount(BaseModel):
    name: str
    type: str
    balance: float
    account_number_last4: Optional[str] = None
    statement_date: Optional[str] = None


class ParsedTransaction(BaseModel):
    date: str
    description: str
    amount: float
    category: Optional[str] = None


class ImportPreview(BaseModel):
    accounts: List[ParsedAccount]
    transactions: List[ParsedTransaction]


class TextPreviewRequest(BaseModel):
    text: str


class ConfirmRequest(BaseModel):
    accounts: List[ParsedAccount]
    transactions: List[ParsedTransaction]


def _account_identity(acct: dict) -> tuple[str, str]:
    """Identity key for deduping the same account across statements.

    Prefer (type, last4) — different physical accounts within the same bank
    have different last4. When last4 is missing fall back to (type, name)
    lowercased + trimmed; this is best-effort but matches how Gemini tends
    to output stable names ("Chase Checking") across the same bank's
    monthly statements.
    """
    last4 = acct.get("account_number_last4")
    if last4:
        return (acct["type"], f"#{last4}")
    name_key = (acct.get("name") or "").strip().lower()
    return (acct["type"], f"name:{name_key}")


def _dedupe_accounts(accounts: list[dict]) -> list[dict]:
    """Within a single upload batch, collapse duplicates of the same account
    that appear in multiple statements. Keep the row whose statement_date is
    latest; rows without a statement_date sort below those that have one,
    so a real closing-date row always wins over an undated one."""
    by_id: dict[tuple[str, str], dict] = {}
    for a in accounts:
        key = _account_identity(a)
        cur = by_id.get(key)
        if cur is None:
            by_id[key] = a
            continue
        # Compare statement_date (None < any string) — empty string sorts
        # before any real YYYY-MM-DD so a dated row always wins.
        cur_d = cur.get("statement_date") or ""
        new_d = a.get("statement_date") or ""
        if new_d > cur_d:
            by_id[key] = a
    return list(by_id.values())


def _parse_both(text: str) -> ImportPreview:
    accounts = parse_accounts_from_text(text)
    transactions = parse_transactions_from_text(text)
    if not accounts and not transactions:
        raise HTTPException(422, "No accounts or transactions found. Try being more specific.")
    return ImportPreview(accounts=_dedupe_accounts(accounts), transactions=transactions)


@router.post("/preview", response_model=ImportPreview)
async def preview_from_text(body: TextPreviewRequest, user=Depends(get_current_user)):
    if not body.text.strip():
        raise HTTPException(400, "Text cannot be empty")
    try:
        return _parse_both(body.text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(422, f"Could not parse: {e}")


@router.post("/file-preview", response_model=ImportPreview)
async def preview_from_file(
    files: List[UploadFile] = File(...),
    user=Depends(get_current_user),
):
    if not files:
        raise HTTPException(400, "At least one file is required")

    accounts: list = []
    transactions: list = []

    for file in files:
        filename = (file.filename or "").lower()
        ext = next((e for e in _SUPPORTED_EXTENSIONS if filename.endswith(e)), None)
        if not ext:
            raise HTTPException(415, f"{file.filename}: only PDF, CSV, or TXT files are supported")

        file_bytes = await file.read()
        if len(file_bytes) > _MAX_FILE_MB * 1024 * 1024:
            raise HTTPException(413, f"{file.filename}: file too large (max {_MAX_FILE_MB} MB)")

        try:
            text = extract_pdf_text(file_bytes) if ext == ".pdf" else extract_csv_text(file_bytes)
        except Exception as e:
            raise HTTPException(422, f"{file.filename}: could not read file: {e}")

        if not text.strip():
            raise HTTPException(422, f"{file.filename}: no text could be extracted")

        # Parse this file in isolation. An individual file yielding no
        # accounts/transactions is tolerated — multi-file uploads commonly
        # mix statements and supporting docs. The aggregate emptiness check
        # below is what surfaces the user-visible error.
        try:
            file_accounts = parse_accounts_from_text(text)
            file_transactions = parse_transactions_from_text(text)
        except Exception as e:
            raise HTTPException(422, f"{file.filename}: could not parse: {e}")

        accounts.extend(file_accounts)
        transactions.extend(file_transactions)

    if not accounts and not transactions:
        raise HTTPException(422, "No accounts or transactions found in the uploaded files.")

    return ImportPreview(accounts=_dedupe_accounts(accounts), transactions=transactions)


@router.post("/confirm")
async def confirm_import(body: ConfirmRequest, user=Depends(get_current_user)):
    uid = str(user.id)
    db = _db()

    # Upsert accounts: if the user already has an account with the same
    # identity (type+last4 when last4 known, otherwise type+name), update
    # its balance instead of creating a duplicate row. This makes monthly
    # re-uploads idempotent across upload sessions, complementing the
    # within-batch dedupe done at preview time.
    existing_rows = (
        db.table("accounts")
        .select("id,name,type,balance,account_number_last4,balance_updated_at,created_at")
        .eq("user_id", uid)
        .execute()
        .data
        or []
    )
    existing_by_key: dict[tuple[str, str], dict] = {}
    for row in existing_rows:
        existing_by_key[_account_identity(row)] = row

    accounts_created = 0
    accounts_updated = 0
    for acct in body.accounts:
        identity = _account_identity(acct.model_dump())
        existing = existing_by_key.get(identity)
        if existing:
            update_payload: dict = {"balance": acct.balance}
            update_payload.update(cache_patch(existing, acct.balance))
            # If user previously had no last4 on the row but the parser found
            # one, fill it in. Don't overwrite a stored last4 that already
            # disambiguates the row.
            if not existing.get("account_number_last4") and acct.account_number_last4:
                update_payload["account_number_last4"] = acct.account_number_last4
            db.table("accounts").update(update_payload).eq("id", existing["id"]).execute()
            if acct.balance is not None and float(existing.get("balance") or 0) != float(acct.balance):
                record_history(
                    db, account_id=existing["id"], user_id=uid,
                    balance=acct.balance, source="file_import",
                )
            accounts_updated += 1
        else:
            insert_payload: dict = {
                "user_id": uid,
                "name": acct.name,
                "type": acct.type,
                "balance": acct.balance,
                "account_number_last4": acct.account_number_last4,
                "source": "manual",
            }
            insert_payload.update(cache_patch(None, acct.balance))
            row = db.table("accounts").insert(insert_payload).execute().data[0]
            record_history(
                db, account_id=row["id"], user_id=uid,
                balance=acct.balance, source="file_import",
            )
            accounts_created += 1

    # Save transactions (no account_id for file/text imports).
    # Skip rows that already exist for this user with the same (date, amount,
    # description) under source=manual — re-uploading the same statement is
    # the common case and we don't want duplicate rows.
    transactions_created = 0
    transactions_skipped = 0
    for txn in body.transactions:
        existing = (
            db.table("transactions")
            .select("id")
            .eq("user_id", uid)
            .eq("source", "manual")
            .eq("date", txn.date)
            .eq("amount", txn.amount)
            .eq("description", txn.description)
            .limit(1)
            .execute()
            .data
        )
        if existing:
            transactions_skipped += 1
            continue
        db.table("transactions").insert({
            "user_id": uid,
            "date": txn.date,
            "description": txn.description,
            "amount": txn.amount,
            "category": txn.category,
            "source": "manual",
        }).execute()
        transactions_created += 1

    if transactions_created:
        safe_scan_transfers_for_user(db, uid)

    return {
        "ok": True,
        "accounts_created": accounts_created,
        "accounts_updated": accounts_updated,
        "transactions_created": transactions_created,
        "transactions_skipped": transactions_skipped,
    }
