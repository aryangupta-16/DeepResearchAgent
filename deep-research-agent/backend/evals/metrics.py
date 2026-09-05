"""Eval harness (Phase B1): golden-set evaluation for the deep-research pipeline.

Deliberately separate from ``app/`` — evals measure the system from the
outside, like a test suite for quality. Two tiers:

- **mocked (every PR, free, deterministic):** scores the ``simulated_report``
  embedded in each golden case — keeps the scoring machinery + gates honest.
- **live (nightly):** runs the real synthesizer agent against a real provider,
  then applies the identical deterministic metrics plus an optional LLM-judge
  citation-precision check. Judge scores are for *relative* trend comparison
  only — too noisy for absolute thresholds.

Artifacts: ``evals/results/eval-score-<timestamp>.json`` (CI-uploadable).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
GOLDEN_SET_PATH = EVALS_DIR / "golden_set.jsonl"
RESULTS_DIR = EVALS_DIR / "results"


@dataclass
class CaseScore:
    """Scores for one golden case."""

    case_id: str
    integrity_violations: list[str] = field(default_factory=list)
    citation_precision: float = 0.0
    rubric_pass: bool = False
    rubric_failures: list[str] = field(default_factory=list)


@dataclass
class EvalRunResult:
    """Aggregate result of one golden-set run."""

    tier: str
    total_cases: int
    mean_citation_precision: float
    cases_with_violations: int
    rubric_pass_rate: float
    passed: bool
    per_case: list[CaseScore] = field(default_factory=list)


def load_golden_set(path: Path | None = None) -> list[dict]:
    """Load and validate the versioned golden set (JSONL)."""
    target = path or GOLDEN_SET_PATH
    cases: list[dict] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def score_case(case: dict, report: dict) -> CaseScore:
    """Score one report against one golden case (deterministic metrics).

    - **citation integrity:** every cited source id must exist in the case's
      provided source set (the structural core of the DB-backed validator).
    - **citation precision (deterministic proxy):** fraction of the expected
      must-cite sources actually cited. The live tier additionally runs an
      LLM-as-judge check on whether each excerpt supports its claim.
    - **report rubric:** structural grounding/coverage checks.
    """
    valid_ids = {s["id"] for s in case["sources"]}
    cited: set[str] = set()
    for section in report.get("sections", []):
        cited.update(section.get("citation_source_ids", []))

    violations = sorted(c for c in cited if c not in valid_ids)

    must = set(case["expected"]["must_cite_source_ids"])
    precision = (len(cited & must) / len(must)) if must else 1.0

    rubric_failures: list[str] = []
    if not report.get("title"):
        rubric_failures.append("missing title")
    if not report.get("summary"):
        rubric_failures.append("missing summary")
    sections = report.get("sections", [])
    if not sections:
        rubric_failures.append("no sections")
    for i, section in enumerate(sections):
        if not section.get("content"):
            rubric_failures.append(f"section {i} empty")
        if not section.get("citation_source_ids"):
            rubric_failures.append(f"section {i} uncited")

    return CaseScore(
        case_id=case["id"],
        integrity_violations=violations,
        citation_precision=round(precision, 4),
        rubric_pass=not rubric_failures,
        rubric_failures=rubric_failures,
    )


def aggregate(tier: str, scores: list[CaseScore]) -> EvalRunResult:
    """Aggregate per-case scores into a run result with a pass/fail gate.

    Gate semantics:
    - regular cases must have **zero** integrity violations (hard, deterministic)
      and a perfect rubric pass rate;
    - ``*-broken`` canary cases must have **at least one** violation — they
      intentionally cite bogus sources and exist to prove the metric catches
      violations (eval-of-the-evals).
    Judge-precision thresholds are deliberately NOT enforced: LLM-judge scores
    are for relative trend comparison only.
    """
    def _is_canary(score: CaseScore) -> bool:
        return score.case_id.endswith("-broken")

    regular = [s for s in scores if not _is_canary(s)]
    canaries = [s for s in scores if _is_canary(s)]
    n = max(1, len(scores))
    mean_precision = round(sum(s.citation_precision for s in scores) / n, 4)
    rubric_rate = round(sum(1 for s in scores if s.rubric_pass) / n, 4)

    clean = all(not s.integrity_violations for s in regular)
    canaries_detected = all(s.integrity_violations for s in canaries)
    passed = clean and canaries_detected and rubric_rate == 1.0
    return EvalRunResult(
        tier=tier,
        total_cases=len(scores),
        mean_citation_precision=mean_precision,
        cases_with_violations=sum(1 for s in scores if s.integrity_violations),
        rubric_pass_rate=rubric_rate,
        passed=passed,
        per_case=scores,
    )


def run_mocked() -> EvalRunResult:
    """Mocked tier: score each case's simulated report (free, deterministic)."""
    scores = [score_case(c, c["simulated_report"]) for c in load_golden_set()]
    return aggregate("mocked", scores)


def write_artifact(result: EvalRunResult, results_dir: Path | None = None) -> Path:
    """Persist one run as a JSON artifact (uploaded by CI)."""
    out_dir = results_dir or RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    path = out_dir / f"eval-score-{result.tier}-{stamp}.json"
    path.write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path
