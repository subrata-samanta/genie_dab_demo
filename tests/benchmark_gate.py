"""Benchmark gate: run every benchmark question of a deployed space (Genie benchmark evaluation) and fail
unless enough are answered correctly.

Genie compares the result of its SQL with the benchmark's expected SQL: GOOD (same result), BAD (different)
or NEEDS_REVIEW (could not be compared automatically; not counted). The gate fails when the run does not
finish, when nothing could be graded, or when accuracy on the graded questions is below
ACCURACY_THRESHOLD (default 0.80, the level Databricks suggests before user acceptance testing).

    export GENIE_SPACE_ID=...        # the space to evaluate
    python tests/benchmark_gate.py

Writes a results table to $GITHUB_STEP_SUMMARY when it is set.
Auth: the standard DATABRICKS_* environment variables or CLI profile. Requires: pip install databricks-sdk
"""
from __future__ import annotations

import os
import sys
import time

from databricks.sdk import WorkspaceClient

TIMEOUT_S = int(os.environ.get("GATE_TIMEOUT_SECONDS", "1800"))
POLL_S = int(os.environ.get("GATE_POLL_SECONDS", "10"))


def _value(x):
    return getattr(x, "value", x)


def run_benchmarks(w: WorkspaceClient, space_id: str) -> list[tuple[str, str, str]]:
    run = w.genie.genie_create_eval_run(space_id)
    print(f"Benchmark run started: {run.eval_run_id}")
    deadline = time.time() + TIMEOUT_S
    while _value(run.eval_run_status) in (None, "NOT_STARTED", "RUNNING"):
        if time.time() > deadline:
            sys.exit(f"GATE FAILED: the benchmark run did not finish within {TIMEOUT_S}s")
        time.sleep(POLL_S)
        run = w.genie.genie_get_eval_run(space_id, run.eval_run_id)
    if _value(run.eval_run_status) != "DONE":
        sys.exit(f"GATE FAILED: the benchmark run ended with status {_value(run.eval_run_status)}")
    results, token = [], None
    while True:
        page = w.genie.genie_list_eval_results(space_id, run.eval_run_id, page_size=100, page_token=token)
        for r in page.eval_results or []:
            d = w.genie.genie_get_eval_result_details(space_id, run.eval_run_id, r.result_id)
            reasons = ", ".join(str(_value(x)) for x in (d.assessment_reasons or []))
            results.append((r.question, _value(d.assessment) or "NEEDS_REVIEW", reasons))
        token = page.next_page_token
        if not token:
            return results


def main() -> int:
    space_id = os.environ.get("GENIE_SPACE_ID")
    if not space_id:
        sys.exit("GENIE_SPACE_ID is not set (see the top of this file).")
    threshold = float(os.environ.get("ACCURACY_THRESHOLD", "0.80"))
    results = run_benchmarks(WorkspaceClient(), space_id)
    good = sum(1 for _, a, _ in results if a == "GOOD")
    bad = sum(1 for _, a, _ in results if a == "BAD")
    graded = good + bad
    accuracy = good / graded if graded else 0.0
    marks = {"GOOD": "PASS", "BAD": "FAIL", "NEEDS_REVIEW": "REVIEW"}
    headline = (f"Benchmarks: {good}/{graded} graded correct ({accuracy:.0%}, threshold {threshold:.0%}), "
                f"{len(results) - graded} need review")
    print("\n" + headline)
    for question, assessment, reasons in results:
        print(f"  [{marks.get(assessment, '?'):^6}] {question}" + (f"  [{reasons}]" if assessment == "BAD" and reasons else ""))
    if not graded:
        verdict = "GATE FAILED: no benchmark could be graded automatically (add benchmarks with a SQL answer)"
    elif accuracy < threshold:
        verdict = f"GATE FAILED: accuracy {accuracy:.0%} < threshold {threshold:.0%}"
    else:
        verdict = "Gate passed."
    print("\n" + verdict)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(f"### {headline}\n\n| Result | Question | Reason |\n|---|---|---|\n")
            for question, assessment, reasons in results:
                fh.write(f"| {marks.get(assessment, '?')} | {question} | {reasons if assessment == 'BAD' else ''} |\n")
            fh.write(f"\n**{verdict}**\n")
    return 0 if verdict == "Gate passed." else 1


if __name__ == "__main__":
    sys.exit(main())
