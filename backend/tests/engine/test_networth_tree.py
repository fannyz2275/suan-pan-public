from app.engine.networth_tree import format_account_label


def test_format_account_label_uses_nickname_when_present():
    a = {"name": "Chase Total Checking", "nickname": "Joint", "account_number_last4": "7890"}
    assert format_account_label(a) == "Joint (*7890)"


def test_format_account_label_falls_back_to_name_when_no_nickname():
    a = {"name": "Marcus Savings", "account_number_last4": "0103"}
    assert format_account_label(a) == "Marcus Savings (*0103)"


def test_format_account_label_omits_suffix_when_account_number_missing():
    a = {"name": "Property"}
    assert format_account_label(a) == "Property"


def test_format_account_label_omits_suffix_when_account_number_last4_invalid():
    a = {"name": "Petty Cash", "account_number_last4": "12"}
    assert format_account_label(a) == "Petty Cash"


def test_format_account_label_handles_missing_name_and_nickname():
    assert format_account_label({}) == "(unnamed)"
    assert format_account_label({"account_number_last4": "9999"}) == "(unnamed) (*9999)"


from app.engine.networth_tree import build_networth_tree


def _checking(uuid="a-1", name="Chase", balance=1000, acct_no="1234"):
    return {"id": uuid, "type": "checking", "name": name,
            "balance": balance, "account_number_last4": acct_no}


def _savings(uuid="a-2", name="Marcus", balance=4000, acct_no="5678"):
    return {"id": uuid, "type": "savings", "name": name,
            "balance": balance, "account_number_last4": acct_no}


def _brokerage(uuid="a-3", name="Schwab", balance=20000, acct_no="9988"):
    return {"id": uuid, "type": "brokerage", "name": name,
            "balance": balance, "account_number_last4": acct_no}


def _debt(uuid="a-4", name="Chase Card", balance=-1500, acct_no="2200"):
    return {"id": uuid, "type": "debt", "name": name,
            "balance": balance, "account_number_last4": acct_no}


def test_tree_has_root_and_four_class_children_in_fixed_order():
    tree = build_networth_tree([])
    assert tree["id"] == "root"
    assert tree["name"] == "Net Worth"
    assert tree["kind"] == "root"
    assert [c["id"] for c in tree["children"]] == [
        "liquid", "investments", "non_current", "liabilities",
    ]


def test_class_node_shape_when_empty():
    tree = build_networth_tree([])
    liquid = tree["children"][0]
    assert liquid["name"] == "Liquid Assets"
    assert liquid["kind"] == "class"
    assert liquid["value"] == 0
    assert liquid["signed_value"] == 0
    # Empty class has no type children
    assert "children" not in liquid or liquid["children"] == []


def test_type_node_appears_only_when_account_exists():
    tree = build_networth_tree([_checking()])
    liquid = tree["children"][0]
    type_ids = [t["id"] for t in liquid["children"]]
    assert "checking" in type_ids
    assert "savings" not in type_ids


def test_account_leaf_shape():
    tree = build_networth_tree([_checking(uuid="acc-1", balance=1234, acct_no="7890")])
    leaf = tree["children"][0]["children"][0]["children"][0]
    assert leaf["id"] == "acc-1"
    assert leaf["kind"] == "account"
    assert leaf["account_type"] == "checking"
    assert leaf["value"] == 1234
    assert leaf["signed_value"] == 1234
    assert leaf["name"].endswith("(*7890)")
    # Leaves never have children
    assert "children" not in leaf


def test_type_value_sums_account_values():
    tree = build_networth_tree([
        _checking(uuid="a", balance=1000),
        _checking(uuid="b", balance=2500),
    ])
    checking = tree["children"][0]["children"][0]
    assert checking["value"] == 3500
    assert len(checking["children"]) == 2


def test_class_value_sums_type_values():
    tree = build_networth_tree([
        _checking(balance=1000),
        _savings(balance=4000),
    ])
    liquid = tree["children"][0]
    assert liquid["value"] == 5000


def test_root_value_sums_signed_class_values():
    # Liquid 1000 + Brokerage 20000 - Debt 1500 = 19500
    tree = build_networth_tree([
        _checking(balance=1000), _brokerage(balance=20000), _debt(balance=-1500),
    ])
    assert tree["signed_value"] == 19500
    assert tree["value"] == 19500


def test_investments_class_includes_brokerage_and_retirement():
    accounts = [
        _brokerage(uuid="b", balance=10000),
        {"id": "r", "type": "retirement", "name": "Fidelity", "balance": 50000, "account_number_last4": "5510"},
    ]
    tree = build_networth_tree(accounts)
    investments = tree["children"][1]
    type_ids = [t["id"] for t in investments["children"]]
    assert "brokerage" in type_ids
    assert "retirement" in type_ids
    assert investments["value"] == 60000


def test_liability_class_uses_negative_signed_value():
    tree = build_networth_tree([_debt(balance=-1500)])
    liabilities = tree["children"][3]
    assert liabilities["value"] == 1500          # display value positive
    assert liabilities["signed_value"] == -1500  # signed contribution negative


def test_liability_type_and_leaves_also_use_negative_signed_value():
    tree = build_networth_tree([_debt(uuid="d1", balance=-2000)])
    debt_type = tree["children"][3]["children"][0]
    assert debt_type["signed_value"] == -2000
    leaf = debt_type["children"][0]
    assert leaf["value"] == 2000
    assert leaf["signed_value"] == -2000


def test_root_can_be_negative_when_debts_exceed_assets():
    tree = build_networth_tree([
        _checking(balance=500), _debt(uuid="d", balance=-2000),
    ])
    assert tree["signed_value"] == -1500
    assert tree["value"] == 1500   # absolute display value


def test_property_uses_estimated_value_not_balance():
    accounts = [{
        "id": "p1", "type": "property", "name": "House",
        "balance": 0, "estimated_value": 750000, "account_number_last4": None,
    }]
    tree = build_networth_tree(accounts)
    non_current = tree["children"][2]
    assert non_current["value"] == 750000
    leaf = non_current["children"][0]["children"][0]
    assert leaf["value"] == 750000


def test_rsu_uses_share_count_times_grant_price():
    accounts = [{
        "id": "r1", "type": "rsu", "name": "Acme RSU",
        "balance": 0,
        "vested_shares": 100, "unvested_shares": 50, "grant_price": 80,
    }]
    tree = build_networth_tree(accounts)
    rsu_leaf = tree["children"][2]["children"][0]["children"][0]
    assert rsu_leaf["value"] == 12000  # (100 + 50) * 80


def test_business_uses_valuation_times_ownership_pct():
    accounts = [{
        "id": "b1", "type": "business", "name": "LLC",
        "balance": 0, "estimated_valuation": 500000, "ownership_pct": 30,
    }]
    tree = build_networth_tree(accounts)
    business_leaf = tree["children"][2]["children"][0]["children"][0]
    assert business_leaf["value"] == 150000


def test_account_leaves_sorted_by_value_desc_then_name_asc():
    tree = build_networth_tree([
        _checking(uuid="z", name="Zebra", balance=100, acct_no="0001"),
        _checking(uuid="a", name="Apple",  balance=500, acct_no="0002"),
        _checking(uuid="m", name="Mango",  balance=500, acct_no="0003"),
    ])
    leaves = tree["children"][0]["children"][0]["children"]
    # 500/Apple, 500/Mango, then 100/Zebra
    assert [l["id"] for l in leaves] == ["a", "m", "z"]
