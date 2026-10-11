"""Smoke test: can the deployed space answer at all?

Asks a few questions through the Genie Conversation API and requires each answer to contain SQL that
returns at least one row. It catches a space that deploys but can't work (missing tables or grants,
empty data, a broken instruction). It does not check that the numbers are right: that is the
benchmark gate's job.

The questions are SMOKE_QUESTIONS (one per line) or, by default, up to three questions that have a trusted
example SQL in the space (the ones Genie answers most reliably); failing that, benchmark questions.

    export GENIE_SPACE_ID=$(databricks bundle summary -t dev -o json | jq -r '.resources.genie_spaces.genie_space.id')
    python tests/smoke_test.py

Auth: the standard DATABRICKS_* environment variables or CLI profile. Requires: pip install databricks-sdk
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from databricks.sdk import WorkspaceClient

SPACE_FILE = Path(__file__).resolve().parent.parent / "src" / "genie_space.geniespace.json"


def questions() -> list[str]:
    if os.environ.get("SMOKE_QUESTIONS", "").strip():
        return [q.strip() for q in os.environ["SMOKE_QUESTIONS"].splitlines() if q.strip()]
    space = json.loads(SPACE_FILE.read_text(encoding="utf-8"))
    examples = [e for e in (space.get("instructions") or {}).get("example_question_sqls", []) if not e.get("parameters")]
    bench = [b for b in (space.get("benchmarks") or {}).get("questions", [])
             if any(a.get("format") == "SQL" for a in b.get("answer", []))]
    picked = examples or bench
    return ["".join(q["question"]) for q in picked[:3]]


def row_count(w: WorkspaceClient, message) -> int:
    """Rows returned by the first SQL answer in a Genie reply (0 when there is none)."""
    for attachment in message.attachments or []:
        if attachment.query is None or not attachment.query.query:
            continue
        result = w.genie.get_message_attachment_query_result(
            message.space_id, message.conversation_id, message.message_id, attachment.attachment_id
        ).statement_response
        if result is None:
            return 0
        if result.manifest and result.manifest.total_row_count is not None:
            return result.manifest.total_row_count
        return len(result.result.data_array or []) if result.result else 0
    return 0


DONE = {"COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"}
HINT = ("Genie runs the question as this job's service principal: it needs CAN USE on the space's SQL warehouse "
        "and USE CATALOG / USE SCHEMA / SELECT on the space's tables (and EXECUTE on its functions).")


def ask(w: WorkspaceClient, space_id: str, question: str, timeout_s: int = 300):
    """Ask a question; return the final message (also when Genie fails, so its error can be shown)."""
    started = w.genie.start_conversation(space_id, question).response
    deadline = time.time() + timeout_s
    while True:
        message = w.genie.get_message(space_id, started.conversation_id, started.message_id)
        status = getattr(message.status, "value", message.status)
        if status in DONE or time.time() > deadline:
            return message, status
        time.sleep(3)


def main() -> int:
    space_id = os.environ.get("GENIE_SPACE_ID")
    if not space_id:
        sys.exit("GENIE_SPACE_ID is not set (see the top of this file).")
    w = WorkspaceClient()
    asked = questions()
    if not asked:
        print("SMOKE TEST FAILED: there is nothing to ask.\n"
              "The space has no trusted example SQL and no benchmark question with a SQL answer, so this "
              "test cannot tell whether it works. Add trusted example SQL and benchmarks in the dev space "
              "(they are also what the QA gate grades), or set SMOKE_QUESTIONS to ask something specific.")
        return 1
    failures = []
    for question in asked:
        message, status = ask(w, space_id, question)
        rows = row_count(w, message) if status == "COMPLETED" else 0
        print(f"[{'PASS' if rows else 'FAIL'}] {question}  ({status}, {rows} row(s))")
        if message.error is not None:
            kind = getattr(message.error.type, "value", message.error.type)
            print(f"       Genie error ({kind}): {message.error.error}")
        if not rows:
            failures.append(question)
    if failures:
        print(f"\nSMOKE TEST FAILED: no usable answer for {len(failures)} question(s).\n{HINT}")
        return 1
    print("\nAll smoke questions answered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
