import datetime
import logging

import plaid
from fastapi import APIRouter, Depends
from plaid.api import plaid_api
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.transactions_get_request import TransactionsGetRequest
from pydantic import BaseModel

from app.auth.middleware import get_current_user
from app.config import settings
from app.db import get_admin_db as _db
from app.engine.transfers import safe_scan_transfers_for_user
from app.finance.balance_history import cache_patch, record_history

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plaid", tags=["plaid"])


_ENV_MAP = {
    "sandbox": plaid.Environment.Sandbox,
    "production": plaid.Environment.Production,
}

from app.advisor.categories import DB_TRANSACTION_CATEGORIES

_TRANSACTION_CATEGORIES = frozenset(DB_TRANSACTION_CATEGORIES)


def _plaid_client():
    cfg = plaid.Configuration(
        host=_ENV_MAP.get(settings.plaid_env, plaid.Environment.Sandbox),
        api_key={"clientId": settings.plaid_client_id, "secret": settings.plaid_secret},
    )
    return plaid_api.PlaidApi(plaid.ApiClient(cfg))


def _map_plaid_category(categories: list) -> str:
    cat = (categories[0] if categories else "").lower()
    if any(k in cat for k in ("food", "restaurant", "dining", "grocer")):
        return "food"
    if any(k in cat for k in ("travel", "transport", "taxi", "gas station", "parking")):
        return "transport"
    if any(k in cat for k in ("shop", "retail", "clothing", "electronics")):
        return "shopping"
    if any(k in cat for k in ("entertain", "recreation", "sport", "gym")):
        return "entertainment"
    if any(k in cat for k in ("health", "medical", "pharmacy", "doctor")):
        return "healthcare"
    if any(k in cat for k in ("housing", "rent", "mortgage")):
        return "housing"
    if any(k in cat for k in ("util", "electric", "water", "internet", "phone")):
        return "utilities"
    if any(k in cat for k in ("transfer", "payment", "payroll", "deposit")):
        return "transfer"
    if any(k in cat for k in ("income", "salary", "wage")):
        return "income"
    return "other"


@router.post("/link-token")
async def create_link_token(user=Depends(get_current_user)):
    request = LinkTokenCreateRequest(
        products=[Products("transactions"), Products("investments")],
        client_name="Suan-Pan",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=str(user.id)),
    )
    response = _plaid_client().link_token_create(request)
    return {
        "link_token": response["link_token"],
        "environment": "production" if settings.plaid_env == "production" else "sandbox",
    }


class ExchangeRequest(BaseModel):
    public_token: str
    institution_name: str


@router.post("/exchange")
async def exchange_token(body: ExchangeRequest, user=Depends(get_current_user)):
    uid = str(user.id)
    client = _plaid_client()
    db = _db()

    exchange = client.item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=body.public_token)
    )
    access_token = exchange["access_token"]
    item_id = exchange["item_id"]

    db.table("plaid_items").insert({
        "user_id": uid,
        "access_token": access_token,
        "item_id": item_id,
        "institution_name": body.institution_name,
    }).execute()

    # Sync accounts
    accounts_response = client.accounts_get(AccountsGetRequest(access_token=access_token))
    type_map = {
        "depository": "savings",
        "investment": "brokerage",
        "credit": "debt",
        "loan": "debt",
    }
    plaid_to_our: dict[str, str] = {}  # plaid_account_id → our DB account id
    for acct in accounts_response["accounts"]:
        plaid_type = acct["type"].value
        our_type = type_map.get(plaid_type, "checking")
        if plaid_type == "depository" and "checking" in acct["name"].lower():
            our_type = "checking"
        balance = acct["balances"]["current"] or 0
        if our_type == "debt":
            balance = -abs(balance)

        # Plaid sometimes carries last_updated_datetime; default to now() if absent.
        plaid_as_of = acct["balances"].get("last_updated_datetime")
        as_of_dt = plaid_as_of or datetime.datetime.now(datetime.timezone.utc)

        insert_payload = {
            "user_id": uid,
            "name": acct["name"],
            "type": our_type,
            "balance": balance,
            "source": "plaid",
            "plaid_account_id": acct["account_id"],
        }
        insert_payload.update(cache_patch(None, balance))
        row = db.table("accounts").insert(insert_payload).execute().data[0]
        record_history(
            db, account_id=row["id"], user_id=uid,
            balance=balance, source="plaid", as_of=as_of_dt,
        )
        plaid_to_our[acct["account_id"]] = row["id"]

    # Sync last 90 days of transactions
    start_date = datetime.date.today() - datetime.timedelta(days=90)
    end_date = datetime.date.today()
    txn_response = client.transactions_get(
        TransactionsGetRequest(
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
        )
    )
    transactions_synced = 0
    for txn in txn_response["transactions"]:
        plaid_txn_id = txn["transaction_id"]
        # Skip if already imported (idempotent)
        if db.table("transactions").select("id").eq("plaid_transaction_id", plaid_txn_id).execute().data:
            continue
        # Plaid: positive = debit (money out), negative = credit (money in) — flip sign
        amount = -float(txn["amount"])
        category = _map_plaid_category(txn.get("category") or [])
        # Per-user categorization policy: if the user has a sticky override
        # for this description, it wins over Plaid's mapping. Falls through
        # to the Plaid category on lookup failure.
        from app.policy import categorize as policy_categorize
        category = policy_categorize.apply(
            db, user_id=uid, description=txn["name"], default_category=category,
        )
        our_account_id = plaid_to_our.get(txn["account_id"])
        db.table("transactions").insert({
            "user_id": uid,
            "account_id": our_account_id,
            "date": str(txn["date"]),
            "description": txn["name"],
            "amount": amount,
            "category": category,
            "source": "plaid",
            "plaid_transaction_id": plaid_txn_id,
        }).execute()
        transactions_synced += 1

    if transactions_synced:
        safe_scan_transfers_for_user(db, uid)

    return {
        "ok": True,
        "accounts_synced": len(accounts_response["accounts"]),
        "transactions_synced": transactions_synced,
    }
