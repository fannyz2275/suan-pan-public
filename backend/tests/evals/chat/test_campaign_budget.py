import pytest

from .offline_control import Ledger, BudgetExceeded, InvalidTransition


def test_campaign_cap_includes_prior_spend_other_questions_and_pending(tmp_path):
    path = tmp_path / 'ledger.sqlite'
    with Ledger(path) as ledger:
        ledger.configure_campaign(1_000_000, 59_329, 'previous-ledger-sha')
        for q in ['a', 'b']:
            ledger.add_question(q, {})
            ledger.start_round(q)
        ledger.reserve('a', 'one', 900_000)
        with pytest.raises(BudgetExceeded):
            ledger.reserve('b', 'two', 50_000)
    with Ledger(path) as ledger:
        ledger.settle('one', 1, {})
        with pytest.raises(BudgetExceeded):
            ledger.reserve('b', 'three', 1)
        assert ledger.campaign_summary()['prior_microusd'] == 59_329
        assert ledger.campaign_summary()['spent_microusd'] == 59_330


def test_campaign_configuration_cannot_reset_or_be_added_late(tmp_path):
    with Ledger(tmp_path/'l') as ledger:
        ledger.configure_campaign(1_000_000, 59_329, 'prior')
        with pytest.raises(InvalidTransition):
            ledger.configure_campaign(1_000_000, 0, 'prior')


def test_campaign_overrun_stops_every_question(tmp_path):
    with Ledger(tmp_path/'l') as ledger:
        ledger.configure_campaign(1_000_000, 0, 'prior')
        for q in ['a','b']:
            ledger.add_question(q,{})
            ledger.start_round(q)
        ledger.reserve('a','one',10)
        with pytest.raises(BudgetExceeded):
            ledger.settle('one',11,{})
        with pytest.raises(BudgetExceeded):
            ledger.reserve('b','two',1)
