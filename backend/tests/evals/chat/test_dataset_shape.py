"""Static shape checks on dataset.jsonl + rubrics.yaml."""
import json
from pathlib import Path

import pytest
import yaml

DATASET_PATH = Path(__file__).parent / "dataset.jsonl"
RUBRICS_PATH = Path(__file__).parent / "rubrics.yaml"

REQUIRED_FIELDS = {
    "id", "dataset_version", "tags", "setup", "messages", "expected_tools",
    "forbidden_tools", "expected_signals", "forbidden_signals",
    "judge_prompt_id", "n_runs", "pass_threshold",
}


def _load_rows():
    lines = [l for l in DATASET_PATH.read_text().splitlines() if l.strip()]
    parsed = [json.loads(l) for l in lines]
    header = parsed[0]
    rows = parsed[1:]
    return header, rows


def test_header_declares_v3():
    header, _ = _load_rows()
    assert header == {"dataset_version": "v3"}


def test_every_row_has_required_fields():
    _, rows = _load_rows()
    for row in rows:
        missing = REQUIRED_FIELDS - row.keys()
        assert not missing, f"row {row.get('id')} missing fields: {missing}"


def test_ids_are_unique():
    _, rows = _load_rows()
    ids = [r["id"] for r in rows]
    assert len(set(ids)) == len(ids), "duplicate id(s) in dataset"


def test_weights_sum_to_one():
    _, rows = _load_rows()
    for row in rows:
        total = sum(s["weight"] for s in row["expected_signals"])
        assert abs(total - 1.0) < 1e-6, f"row {row['id']} weights sum to {total}"


def test_judge_prompt_ids_exist_in_rubrics():
    _, rows = _load_rows()
    rubrics = yaml.safe_load(RUBRICS_PATH.read_text())
    for row in rows:
        assert row["judge_prompt_id"] in rubrics, (
            f"row {row['id']} references unknown rubric {row['judge_prompt_id']}"
        )


def test_signal_ids_match_rubric_criteria():
    _, rows = _load_rows()
    rubrics = yaml.safe_load(RUBRICS_PATH.read_text())
    for row in rows:
        rubric = rubrics[row["judge_prompt_id"]]
        criterion_ids = {c["id"] for c in rubric["criteria"]}
        signal_ids = {s["id"] for s in row["expected_signals"]}
        unknown = signal_ids - criterion_ids
        assert not unknown, (
            f"row {row['id']} has signal ids {unknown} not in rubric "
            f"{row['judge_prompt_id']}"
        )


def test_seed_ids_resolve():
    from tests.evals.chat.seeds import SEED_FACTORIES
    _, rows = _load_rows()
    for row in rows:
        seed_id = row["setup"]["seed_id"]
        assert seed_id in SEED_FACTORIES, (
            f"row {row['id']} references unknown seed_id {seed_id}"
        )
