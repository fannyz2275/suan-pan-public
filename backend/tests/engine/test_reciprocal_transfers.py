from app.engine.transfers import detect_pairs_and_orphans


def pair():
    return [dict(id='a', account_id='x', counterparty_account_id='y', user_id='u', currency='USD',
                 counterparty_provenance='user_confirmed', amount=-500, date='2026-09-01'),
            dict(id='b', account_id='y', counterparty_account_id='x', user_id='u', currency='USD',
                 counterparty_provenance='user_confirmed', amount=500, date='2026-09-02')]


def test_reciprocal_pair():
    assert len([d for d in detect_pairs_and_orphans(pair()) if d.new_status == 'auto_paired']) == 2


def test_amount_only_currency_owner_and_identity_do_not_pair():
    for field, value in [('counterparty_account_id', None), ('counterparty_account_id', 'z'),
                         ('currency', 'EUR'), ('user_id', 'other'), ('counterparty_provenance', None)]:
        rows = pair()
        rows[1][field] = value
        assert not any(d.new_status == 'auto_paired' for d in detect_pairs_and_orphans(rows))


def test_duplicate_and_zero_do_not_pair():
    rows = pair()
    rows.append({**rows[1], 'id':'c'})
    assert not any(d.new_status == 'auto_paired' for d in detect_pairs_and_orphans(rows))
    rows = pair()
    for row in rows: row['amount'] = 0
    assert not any(d.new_status == 'auto_paired' for d in detect_pairs_and_orphans(rows))
