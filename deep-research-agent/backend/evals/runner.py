"""Live-tier eval runner: real synthesizer + real provider (nightly).

Usage (requires a real provider key in the environment):
    uv run python -m evals.runner            # live run, writes an artifact
    uv run python -m evals.runner --tier mocked
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass

from app.agents.synthesizer.agent import SynthesizerAgent
from app.common.exceptions import AppError
from app.config.settings import get_settings
from app.llm.factory import get_llm_provider
from evals.metrics import (
    EvalRunResult,
    aggregate,
    load_golden_set,
    run_mocked,
    score_case,
    write_artifact,
)


@dataclass(frozen=True)
class _ResultView:
    """Minimal duck-typed view over a synthesized result for scoring."""

    payload: dict

    def model_dump(self) -> dict:
        return self.payload


async def run_live() -> EvalRunResult:
    """Run the real synthesizer over the golden set, then score identically."""
    provider = get_llm_provider(get_settings())
    synthesizer = SynthesizerAgent(provider)
    scores = []
    for case in load_golden_set():
        evidence_index = {
            s["id"]: {"title": s["title"], "url": s["url"], "evidence": s["evidence"]}
            for s in case["sources"]
        }
        results_payload = [
            {"claim": ev["claim"], "source_id": s["id"]}
            for s in case["sources"]
            for ev in s["evidence"]
        ]
        try:
            report = await synthesizer.run(
                case["query"],
                [_ResultView(payload={"claim": r["claim"], "source_id": r["source_id"]})
                 for r in results_payload],
                evidence_index,
            )
            scores.append(score_case(case, report))
        except AppError as exc:
            print(f"case {case['id']}: synthesis failed: {exc}", file=sys.stderr)
            scores.append(score_case(case, {}))
    return aggregate("live", scores)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run golden-set evals.")
    parser.add_argument("--tier", choices=["mocked", "live"], default="mocked")
    args = parser.parse_args()

    if args.tier == "live" and not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set; cannot run live evals.", file=sys.stderr)
        return 2

    result = asyncio.run(run_live()) if args.tier == "live" else run_mocked()
    artifact = write_artifact(result)
    print(
        f"tier={result.tier} cases={result.total_cases} "
        f"precision={result.mean_citation_precision} "
        f"violations={result.cases_with_violations} "
        f"rubric={result.rubric_pass_rate} passed={result.passed}"
    )
    print(f"artifact: {artifact}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
