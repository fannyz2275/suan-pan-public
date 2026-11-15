from app.provider_credentials.scope import gemini_client
import io
import json
import re
from datetime import date

import pdfplumber
from google import genai

from app.advisor.categories import DB_TRANSACTION_CATEGORIES
from app.config import settings

_ACCOUNT_TYPES = ["checking", "savings", "brokerage", "retirement", "property", "rsu", "business", "debt"]
_TRANSACTION_CATEGORIES = list(DB_TRANSACTION_CATEGORIES)

_ACCOUNT_PROMPT = """<role>
You are a structured-data extractor for a personal finance app. You read raw
text from bank/brokerage/credit-card statements and emit a clean JSON array of
account records. You never guess; you omit fields you can't read.
</role>

<task>
Extract every financial account, asset, or liability described in the text
below. Return ONLY a valid JSON array (no prose, no code fences).
</task>

<critical_rule priority="1">
SIGN CONVENTION — this is the rule most often violated. Read carefully.

  - For ASSETS (checking, savings, brokerage, retirement, property, rsu,
    business): balance is POSITIVE.
  - For DEBTS (credit cards, loans, mortgages, lines of credit): balance is
    NEGATIVE — even though the statement displays it as a positive number.

A credit-card statement saying "Balance: $5,234.12" means the user OWES
$5,234.12. You MUST emit `"balance": -5234.12` with `"type": "debt"`.
A positive balance on a `type: "debt"` row is ALWAYS wrong.
</critical_rule>

<schema>
Each element of the array must have EXACTLY these fields:

  - "name": short descriptive label, e.g. "Chase Checking", "Vanguard Brokerage"
  - "type": one of {account_types}
  - "balance": number, signed per the critical rule above. Closing/as-of
    balance for the statement period — never the opening balance.
  - "account_number_last4": exactly 4 digits as a string, OR null. Only emit
    digits you can read unambiguously (e.g. "Account ending in 1234",
    "...****1234"). If you would have to guess, emit null.
  - "statement_date": "YYYY-MM-DD" of the statement's closing / as-of date
    (e.g. statement period end, "Statement Date", "Balance as of"), OR null
    if not stated. Used to pick the latest balance when the same account
    appears across multiple statements — accuracy matters.
</schema>

<type_inference>
  - checking accounts            -> "checking"
  - savings, money market        -> "savings"
  - 401(k), IRA, pension         -> "retirement"
  - brokerage / investment       -> "brokerage"
  - real estate, property        -> "property"
  - RSU grants, stock options    -> "rsu"
  - private business equity      -> "business"
  - credit cards, loans, mortgages, lines of credit -> "debt"
</type_inference>

<examples>
GOOD - credit card statement:
  Input excerpt: "Chase Sapphire Reserve  Statement Date: 04/30/2026
                  Account ending in 8821  New Balance: $5,234.12"
  Output: [{{"name": "Chase Sapphire Reserve", "type": "debt",
            "balance": -5234.12, "account_number_last4": "8821",
            "statement_date": "2026-04-30"}}]

GOOD - checking statement:
  Input excerpt: "Wells Fargo Everyday Checking  ...1234
                  Closing Balance as of 03/31/2026: $5,000.00"
  Output: [{{"name": "Wells Fargo Everyday Checking", "type": "checking",
            "balance": 5000.00, "account_number_last4": "1234",
            "statement_date": "2026-03-31"}}]

BAD - sign-flipped debt (DO NOT emit this shape):
  [{{"name": "Chase Sapphire Reserve", "type": "debt", "balance": 5234.12, ...}}]
  Positive balance on a debt row is always wrong.

BAD - opening balance instead of closing (DO NOT emit this shape):
  Input excerpt: "Opening Balance: $1,000.00 ... Closing Balance: $5,000.00"
  Wrong output: {{"balance": 1000.00}}
  Correct:      {{"balance": 5000.00}}
</examples>

<other_rules>
  - Omit accounts with no balance information (do not invent zero).
  - Return [] if no accounts are found.
  - Output must be a JSON array, parseable by json.loads - no prose, no
    backticks, no commentary, no trailing commas.
</other_rules>

<text_to_parse>
{text}
</text_to_parse>
"""

_TRANSACTION_PROMPT = """<role>
You are a structured-data extractor for a personal finance app. You read raw
text from bank/credit-card statements (PDF or CSV exports) and emit a clean
JSON array of individual transactions.
</role>

<task>
Extract every individual transaction from the text below. Return ONLY a valid
JSON array (no prose, no code fences). Each row of a transaction table is one
transaction - include ALL of them.
</task>

<critical_rule priority="1">
SIGN CONVENTION - this is the rule most often violated.

  - Money OUT of the account (purchases, fees, withdrawals, debits, expenses):
    `amount` is NEGATIVE.
  - Money IN to the account (payroll, refunds, interest, deposits, credits):
    `amount` is POSITIVE.

The category MUST agree with the sign:
  - category="income"  =>  amount > 0  (PAYROLL, REFUND, INTEREST, DEPOSIT, ...)
  - everything else    =>  amount < 0

A "PAYROLL" row with category="income" and amount=-4200 is ALWAYS wrong - the
sign would silently halve the user's apparent income downstream.
</critical_rule>

<schema>
Each element of the array must have EXACTLY these fields:

  - "date": "YYYY-MM-DD". If the year is not stated in the row, assume {year}.
    Never invent a date; if you truly cannot determine one, use today.
  - "description": concise merchant or transaction description, e.g.
    "Whole Foods", "Payroll Acme Corp". Strip transaction IDs and POS noise.
  - "amount": signed number per the critical rule above.
  - "category": one of {categories}.
</schema>

<column_handling>
  - Separate Debit / Credit columns:
      debit  -> emit `amount` as NEGATIVE (money out)
      credit -> emit `amount` as POSITIVE (money in)
  - Single Amount column where the bank stores credits as negative
    (some brokerage CSVs do this): FLIP the sign so income ends up positive.
  - "Pending" transactions: include them with their stated amount; the app
    handles dedupe against later "posted" rows.
</column_handling>

<examples>
GOOD - payroll deposit:
  Input row: "04/30/2026  PAYROLL ACME CORP  +4,200.00"
  Output: {{"date": "2026-04-30", "description": "Payroll Acme Corp",
            "amount": 4200.00, "category": "income"}}

GOOD - grocery purchase:
  Input row: "04/03/2026  WHOLE FOODS  -142.33"
  Output: {{"date": "2026-04-03", "description": "Whole Foods",
            "amount": -142.33, "category": "food"}}

GOOD - refund (money in, but NOT income):
  Input row: "04/12/2026  AMAZON.COM REFUND  +28.40"
  Output: {{"date": "2026-04-12", "description": "Amazon Refund",
            "amount": 28.40, "category": "shopping"}}
  Rationale: the original purchase was negative `shopping`; the refund offsets
  it in the same category. Refunds are NOT category="income".

BAD - sign-flipped income (DO NOT emit this shape):
  {{"description": "Payroll Acme Corp", "amount": -4200.00, "category": "income"}}
  Negative amount with category="income" is always wrong.

BAD - including summary rows (DO NOT emit these):
  "OPENING BALANCE", "CLOSING BALANCE", "TOTAL DEPOSITS", "TOTAL WITHDRAWALS",
  "STATEMENT TOTAL", page subtotals - these are not transactions.
</examples>

<category_guidance>
  Pick the most specific category that fits. If a row genuinely doesn't fit
  any specific category, use "other" - better than guessing wrong. The app
  monitors the rate of "other" and will flag if it gets too high.

  Use "transfer" only for movement between the user's own accounts (e.g.
  "TRANSFER TO SAVINGS", "ZELLE TO SELF"). Transfers must net to zero across
  the user's accounts; do not categorize external payments as transfers.
</category_guidance>

<other_rules>
  - Skip header rows, page headers, balance totals, account summary lines,
    and opening/closing balance lines.
  - Return [] if no individual transactions are found.
  - Output must be a JSON array, parseable by json.loads - no prose, no
    backticks, no commentary, no trailing commas.
</other_rules>

<text_to_parse>
{text}
</text_to_parse>
"""


def _call_gemini(prompt: str) -> list:
    client = gemini_client()
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    raw = response.text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    result = json.loads(raw)
    return result if isinstance(result, list) else []


_LAST4_RE = re.compile(r"^\d{4}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_accounts_from_text(text: str) -> list[dict]:
    """Extract account balances from any free-form text using Gemini."""
    prompt = _ACCOUNT_PROMPT.format(account_types=_ACCOUNT_TYPES, text=text)
    rows = _call_gemini(prompt)
    result = []
    for a in rows:
        if not isinstance(a, dict):
            continue
        if a.get("type") not in _ACCOUNT_TYPES:
            a["type"] = "checking"
        last4 = a.get("account_number_last4")
        if isinstance(last4, (int, str)):
            last4 = str(last4)
            last4 = last4 if _LAST4_RE.match(last4) else None
        else:
            last4 = None
        stmt_date = a.get("statement_date")
        stmt_date = str(stmt_date) if stmt_date else None
        if stmt_date and not _DATE_RE.match(stmt_date):
            stmt_date = None
        result.append({
            "name": str(a.get("name", "Unnamed Account")),
            "type": a["type"],
            "balance": float(a.get("balance", 0)),
            "account_number_last4": last4,
            "statement_date": stmt_date,
        })
    return result


def parse_transactions_from_text(text: str) -> list[dict]:
    """Extract individual transactions from any free-form text using Gemini."""
    prompt = _TRANSACTION_PROMPT.format(
        year=date.today().year,
        categories=_TRANSACTION_CATEGORIES,
        text=text,
    )
    rows = _call_gemini(prompt)
    result = []
    for t in rows:
        if not isinstance(t, dict):
            continue
        category = t.get("category")
        if category not in _TRANSACTION_CATEGORIES:
            category = "other"
        # Normalize date — accept YYYY-MM-DD or fallback to today
        raw_date = str(t.get("date", ""))
        if not re.match(r"\d{4}-\d{2}-\d{2}", raw_date):
            raw_date = str(date.today())
        result.append({
            "date": raw_date,
            "description": str(t.get("description", "Unknown")),
            "amount": float(t.get("amount", 0)),
            "category": category,
        })
    return result


def extract_pdf_text(file_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages)


def extract_csv_text(file_bytes: bytes) -> str:
    return file_bytes.decode("utf-8", errors="replace")
