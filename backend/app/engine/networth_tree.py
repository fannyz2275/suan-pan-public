from typing import Any, Dict, List

from app.engine.snapshot import (
    DEBT_TYPES,
    INVESTMENT_TYPES,
    LIQUID_TYPES,
    NON_CURRENT_TYPES,
    RETIREMENT_TYPES,
    notional_value,
)


def format_account_label(account: Dict[str, Any]) -> str:
    """Display label for an account leaf.

    Uses `nickname` if set (forward-compat with sub-project #2), otherwise
    `name`, otherwise "(unnamed)". Appends "(*XXXX)" when account_number is
    at least 4 chars long so users can disambiguate same-named accounts.
    """
    name = account.get("nickname") or account.get("name") or "(unnamed)"
    acct_no = account.get("account_number_last4") or ""
    last4 = acct_no[-4:] if len(acct_no) >= 4 else None
    return f"{name} (*{last4})" if last4 else name


# Class definition: (id, display_name, account-type set, is_liability)
CLASSES = [
    ("liquid",       "Liquid Assets",      LIQUID_TYPES,                          False),
    ("investments",  "Investments",        INVESTMENT_TYPES | RETIREMENT_TYPES,   False),
    ("non_current",  "Non-current Assets", NON_CURRENT_TYPES,                     False),
    ("liabilities",  "Liabilities",        DEBT_TYPES,                            True),
]

TYPE_LABELS = {
    "checking": "Checking", "savings": "Savings",
    "brokerage": "Brokerage", "retirement": "Retirement",
    "property": "Property", "rsu": "RSU", "business": "Business",
    "debt": "Debt",
}


def _account_value(account: Dict[str, Any]) -> float:
    """Liability accounts use abs(balance); others use notional_value()."""
    if account.get("type") in DEBT_TYPES:
        return abs(account.get("balance") or 0.0)
    return notional_value(account)


def _build_account_leaf(account: Dict[str, Any], is_liability: bool) -> Dict[str, Any]:
    value = _account_value(account)
    return {
        "id": account.get("id"),
        "name": format_account_label(account),
        "kind": "account",
        "account_type": account.get("type"),
        "value": value,
        "signed_value": -value if is_liability else value,
    }


def _build_type_node(type_id: str, accounts: List[Dict[str, Any]],
                     is_liability: bool) -> Dict[str, Any]:
    leaves = [_build_account_leaf(a, is_liability) for a in accounts]
    leaves.sort(key=lambda n: (-n["value"], n["name"]))
    value = sum(leaf["value"] for leaf in leaves)
    return {
        "id": type_id,
        "name": TYPE_LABELS.get(type_id, type_id.title()),
        "kind": "type",
        "value": value,
        "signed_value": -value if is_liability else value,
        "children": leaves,
    }


def build_networth_tree(accounts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """3-level tree (class → type → account). All four classes always present.

    Type nodes appear only when at least one account has that type. Account
    leaves are sorted by value desc then name asc for deterministic output.
    """
    accounts = accounts or []
    class_nodes: List[Dict[str, Any]] = []
    for class_id, class_name, type_set, is_liability in CLASSES:
        # Bucket accounts by type within this class.
        by_type: Dict[str, List[Dict[str, Any]]] = {}
        for a in accounts:
            t = a.get("type")
            if t in type_set:
                by_type.setdefault(t, []).append(a)
        type_children = [
            _build_type_node(t, by_type[t], is_liability)
            for t in sorted(by_type.keys())
        ]
        class_value = sum(tn["value"] for tn in type_children)
        class_node: Dict[str, Any] = {
            "id": class_id,
            "name": class_name,
            "kind": "class",
            "value": class_value,
            "signed_value": -class_value if is_liability else class_value,
        }
        if type_children:
            class_node["children"] = type_children
        class_nodes.append(class_node)

    root_signed = sum(c["signed_value"] for c in class_nodes)
    return {
        "id": "root",
        "name": "Net Worth",
        "kind": "root",
        "value": abs(root_signed),
        "signed_value": root_signed,
        "children": class_nodes,
    }
