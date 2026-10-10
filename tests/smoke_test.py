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


def main() -> int:
    space_id = os.environ.get("GENIE_SPACE_ID")
    if not space_id:
        sys.exit("GENIE_SPACE_ID is not set (see the top of this file).")
    w = WorkspaceClient()
    failures = []
    for question in questions():
        message = w.genie.start_conversation_and_wait(space_id, question)
        status = getattr(message.status, "value", message.status)
        rows = row_count(w, message) if status == "COMPLETED" else 0
        print(f"[{'PASS' if rows else 'FAIL'}] {question}  ({status}, {rows} row(s))")
        if not rows:
            failures.append(question)
    if failures:
        print(f"\nSMOKE TEST FAILED: no usable answer for {len(failures)} question(s)")
        return 1
    print("\nAll smoke questions answered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
