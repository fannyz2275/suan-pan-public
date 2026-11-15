from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import List, Optional
from uuid import UUID, uuid4

from app.engine.recurring.cluster import CandidateCluster, build_candidate_clusters
from app.engine.recurring.confidence import (
    ConfidenceInputs,
    amount_stability_score,
    composite_confidence,
    description_consistency_score,
    regularity_score,
)
from app.engine.recurring.llm import llm_refine_cluster, should_use_llm
from app.engine.recurring.normalize import jaccard, token_set
from app.engine.recurring.period import infer_current_period, infer_period, passes_minimum_occurrence_gate
from app.engine.recurring.rule_match import apply_rule_matches
from app.engine.recurring.schema import (
    Direction, Frequency, RecurringRule, Source, Status,
)

WINDOW_DAYS = 365
AUTO_APPLY_THRESHOLD = 0.75
REVIEW_THRESHOLD = 0.40
SIGN_EPSILON = 0.0


def _filter_window(transactions: list[dict], today: date) -> list[dict]:
    cutoff = today - timedelta(days=WINDOW_DAYS)
    out = []
    for t in transactions:
        if t.get("transfer_status") in {"auto_paired", "user_confirmed_internal"}:
            continue
        d = t["date"]
        if isinstance(d, str):
            from datetime import datetime
            d = datetime.fromisoformat(d).date()
        if d >= cutoff:
            out.append({**t, "date": d})
    return out


def _effective_window_days(dates: list[date], today: date) -> int:
    if not dates:
        return 1
    earliest = min(dates)
    return max(1, min(WINDOW_DAYS, (today - earliest).days + 1))


def _status_from_confidence(c: float) -> Status:
    if c >= AUTO_APPLY_THRESHOLD:
        return Status.AUTO_APPLIED
    if c >= REVIEW_THRESHOLD:
        return Status.PENDING_REVIEW
    return Status.PROPOSED


def _cluster_to_rule(
    *,
    cluster: CandidateCluster,
    frequency: Frequency,
    direction: Direction,
    confidence: float,
    source: Source,
    user_id: UUID,
) -> RecurringRule:
    abs_amts = [abs(a) for a in cluster.amounts]
    sorted_amts = sorted(abs_amts)
    n = len(sorted_amts)
    p10 = sorted_amts[max(0, int(round(0.10 * (n - 1))))]
    p90 = sorted_amts[min(n - 1, int(round(0.90 * (n - 1))))]
    median_amt = statistics.median(abs_amts)
    # Keyword = most common original description (first N chars), falls back to normalized key.
    most_common_desc = max(set(cluster.descriptions), key=cluster.descriptions.count)
    return RecurringRule(
        user_id=user_id,
        keyword=most_common_desc[:64],
        normalized_key_pattern=cluster.normalized_key,
        amount_min=p10,
        amount_max=p90,
        amount_median=median_amt,
        frequency=frequency,
        direction=direction,
        confidence=round(confidence, 2),
        status=_status_from_confidence(confidence),
        source=source,
        last_seen_date=max(cluster.dates) if cluster.dates else None,
        occurrences_observed=n,
        sample_transaction_ids=[],  # populated by store layer from transaction_ids
    )


def _labeled_match_for_cluster(
    cluster: CandidateCluster,
    active_rules: list[RecurringRule],
    direction: Direction,
    period_freq: Frequency,
) -> bool:
    cluster_tokens = token_set(cluster.normalized_key)
    cluster_median = statistics.median([abs(a) for a in cluster.amounts])
    for r in active_rules:
        if r.status != Status.USER_CONFIRMED:
            continue
        if r.direction != direction:
            continue
        if r.frequency != period_freq:
            continue
        rule_tokens = token_set(r.normalized_key_pattern)
        if jaccard(cluster_tokens, rule_tokens) < 0.6:
            continue
        lo = r.amount_min * 0.8
        hi = r.amount_max * 1.2
        if lo <= cluster_median <= hi:
            return True
    return False


def detect_recurring_rules(
    *,
    transactions: list[dict],
    active_rules: list[RecurringRule],
    user_id: UUID,
    today: Optional[date] = None,
    allow_llm: bool = True,
) -> List[RecurringRule]:
    """Pure detection. Returns the full current-state list of rules (updated + new).

    - active_rules contains any status. Only user_confirmed + auto_applied participate in rule-match.
    - Transactions already matched by rule-match are bound (not reclustered) and their host rule
      appears in the output with updated occurrences_observed and last_seen_date.
    - Remaining transactions are clustered and scored; LLM is called for ambiguous clusters.
    - Output contains both updated existing rules and newly emitted rules.
    """
    today = today or date.today()
    rows = _filter_window(transactions, today)

    # Stage 1 — Rule match.
    rm = apply_rule_matches(rows, active_rules)

    # Update active rules with new bindings.
    rule_map = {r.id: r for r in active_rules}
    rows_by_id = {str(row['id']): row for row in rows}
    bindings_by_rule = {}
    for txn_id, rule_id in rm.bindings.items():
        bindings_by_rule.setdefault(rule_id, []).append(rows_by_id[str(txn_id)])
    for rule_id, matched in bindings_by_rule.items():
        rule = rule_map[rule_id]
        matched.sort(key=lambda row: (row['date'], str(row['id'])))
        rule_map[rule_id] = rule.model_copy(update={
            "occurrences_observed": len(matched),
            "last_seen_date": max(row['date'] for row in matched),
            "sample_transaction_ids": [row['id'] for row in matched[-10:]],
        })
        if rule.status == Status.AUTO_APPLIED:
            observed = infer_current_period([row['date'] for row in matched])
            if observed.frequency and passes_minimum_occurrence_gate(observed.frequency, len(matched)):
                rule_map[rule_id] = rule_map[rule_id].model_copy(update={'frequency':observed.frequency})

    updated_existing = [r for r in rule_map.values()
                        if r.status in (Status.USER_CONFIRMED, Status.AUTO_APPLIED)]

    # Stage 2 — Cluster remaining transactions, per direction.
    remaining = rm.unmatched
    emitted: list[RecurringRule] = []

    for direction in (Direction.EXPENSE, Direction.INCOME):
        clusters = build_candidate_clusters(remaining, direction=direction.value)
        for cluster in clusters:
            period = infer_current_period(cluster.dates)
            if period != infer_period(cluster.dates):
                indices = sorted(range(len(cluster.dates)), key=lambda i: cluster.dates[i])[-4:]
                cluster = CandidateCluster(normalized_key=cluster.normalized_key, **{
                    key: [getattr(cluster, key)[i] for i in indices]
                    for key in ('dates', 'amounts', 'descriptions', 'transaction_ids')
                })
            if period.frequency is None:
                continue
            if not passes_minimum_occurrence_gate(period.frequency, len(cluster.transaction_ids)):
                continue

            reg = regularity_score(period.gaps)
            amt = amount_stability_score(cluster.amounts)
            desc = description_consistency_score(cluster.descriptions)
            eff_window = _effective_window_days(cluster.dates, today)
            labeled = _labeled_match_for_cluster(cluster, active_rules, direction, period.frequency)

            inputs = ConfidenceInputs(
                gaps=period.gaps,
                amounts=cluster.amounts,
                observed_count=len(cluster.transaction_ids),
                period_days=period.median_gap_days,
                effective_window_days=eff_window,
                descriptions=cluster.descriptions,
                labeled_match=labeled,
            )
            confidence = composite_confidence(inputs)

            # Stage 3 — LLM tiebreaker for ambiguous clusters.
            if allow_llm and should_use_llm(
                confidence=confidence,
                description_consistency=desc,
                regularity=reg,
                amount_stability=amt,
            ):
                llm_rule = llm_refine_cluster(
                    cluster=cluster,
                    frequency=period.frequency,
                    direction=direction,
                    heuristic_confidence=confidence,
                    few_shot_rules=[r for r in active_rules if r.status == Status.USER_CONFIRMED],
                    user_id=user_id,
                )
                if llm_rule is not None:
                    emitted.append(llm_rule.model_copy(update={
                        "status": _status_from_confidence(llm_rule.confidence),
                        "last_seen_date": max(cluster.dates),
                    }))
                    continue

            rule = _cluster_to_rule(
                cluster=cluster,
                frequency=period.frequency,
                direction=direction,
                confidence=confidence,
                source=Source.HEURISTIC,
                user_id=user_id,
            )
            # Keep `sample_transaction_ids` empty here; store layer fills from transaction_ids.
            emitted.append(rule.model_copy(update={
                "sample_transaction_ids": [],
            }))

    # Pending/proposed rules are reclustered, but must retain their database
    # identity instead of colliding with the unique pattern/schedule key.
    def identity(rule):
        return (rule.user_id, rule.normalized_key_pattern, rule.frequency, rule.direction)

    existing_by_key = {identity(rule): rule for rule in active_rules}
    active_keys = {identity(rule) for rule in updated_existing}
    reconciled = []
    for rule in emitted:
        key = identity(rule)
        previous = existing_by_key.get(key)
        if key in active_keys or (previous and previous.status == Status.USER_REJECTED):
            continue
        if previous:
            rule = rule.model_copy(update={"id": previous.id})
        reconciled.append(rule)
        active_keys.add(key)
    return updated_existing + reconciled
