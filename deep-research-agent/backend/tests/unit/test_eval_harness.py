"""CI gate for the eval harness (Phase B1 exit criteria).

Runs the mocked tier over the versioned golden set on every PR: free,
deterministic, and it fails the build if citation integrity regresses or the
scoring machinery stops detecting violations (the canary case).
"""

from __future__ import annotations

import json

from evals.metrics import (
    aggregate,
    load_golden_set,
    run_mocked,
    score_case,
    write_artifact,
)


def test_golden_set_loads_and_is_wellformed() -> None:
    cases = load_golden_set()
    assert len(cases) >= 10, "golden set should hold a meaningful sample"
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "case ids must be unique"
    for case in cases:
        assert case["query"] and case["sources"]
        assert case["expected"]["must_cite_source_ids"]
        assert "simulated_report" in case


def test_mocked_run_passes_gate() -> None:
    result = run_mocked()
    assert result.passed, (
        "golden-set gate failed; the harness must remain green on its own "
        "seed data"
    )
    assert result.total_cases == len(load_golden_set())
    assert result.rubric_pass_rate == 1.0


def test_canary_violation_is_detected() -> None:
    """The intentionally-broken case must be flagged — proves the metric works."""
    cases = {c["id"]: c for c in load_golden_set()}
    canary = next(c for c in cases.values() if c["id"].endswith("-broken"))
    score = score_case(canary, canary["simulated_report"])
    assert score.integrity_violations, "canary violation went undetected"
    assert score.citation_precision == 0.0


def test_gate_fails_when_regular_case_violates() -> None:
    """A regression that introduces violations must flip the gate to failed."""
    cases = load_golden_set()
    scores = [score_case(c, c["simulated_report"]) for c in cases]
    # Inject a fake violation into a regular case (simulated regression).
    for s in scores:
        if not s.case_id.endswith("-broken"):
            s.integrity_violations = ["00000000-0000-0000-0000-000000000000"]
            break
    assert not aggregate("mocked", scores).passed


def test_gate_fails_when_canary_is_not_detected() -> None:
    """If the metric stops flagging the canary, the harness itself is broken."""
    cases = load_golden_set()
    scores = [score_case(c, c["simulated_report"]) for c in cases]
    for s in scores:
        if s.case_id.endswith("-broken"):
            s.integrity_violations = []  # simulate detection loss
    assert not aggregate("mocked", scores).passed


def test_artifact_is_wellformed_json(tmp_path) -> None:
    result = run_mocked()
    path = write_artifact(result, results_dir=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["tier"] == "mocked"
    assert payload["passed"] is True
    assert len(payload["per_case"]) == result.total_cases
