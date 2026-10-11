"""Decide whether deploying may replace the live space, from `databricks bundle plan -o json`.

    databricks bundle plan -t dev -o json > plan.json
    python scripts/deploy_guard.py plan.json --on-ui-edits keep|overwrite|refuse
    python scripts/deploy_guard.py plan.json --live-matches      # does the live space equal the local JSON?

`bundle deploy` replaces the live space with the JSON from git. The plan shows whether the live space
was edited in the UI since the last deployment (the etag it remembers differs from the live etag),
and the live content (remote_state.serialized_space).

  keep       (dev)  if the live space has UI edits that are not in git yet, do not deploy: they would be
                    lost. They will arrive in the next dev-sync pull request. Otherwise deploy.
  overwrite  (qa)   deploy anyway, but report the UI edits that are overwritten.
  refuse     (prod) stop (exit 2) if the live space was edited in the UI; nobody should edit prod.

Writes `deploy=true|false` (or, with --live-matches, `matches=true|false`) to $GITHUB_OUTPUT and a note
to $GITHUB_STEP_SUMMARY.
Exit 3 if the plan would delete or recreate the space (its URL and conversations would be lost).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import describe_changes as D                                               # noqa: E402
import space_lib as S                                                      # noqa: E402

KEY = "resources.genie_spaces.genie_space"


def decide(plan: dict, local: dict, policy: str) -> tuple[str, bool, str]:
    """(verdict, deploy?, explanation); verdict is ok | keep | overwrite | refuse | destroy."""
    entry = (plan.get("plan") or {}).get(KEY)
    if entry is None:
        return "ok", True, "the space is not in the plan"
    action = entry.get("action")
    if action in ("delete", "recreate"):
        return "destroy", False, f"the plan would {action} the Genie space: its URL and conversations would be lost"
    if action == "create":
        twin = existing_space_titled(title_of(entry))
        if twin:
            return "destroy", False, (
                f"the plan would CREATE a space, but {twin[1]!r} already exists in this workspace "
                f"(id {twin[0]}). Deploying would make a second, duplicate space and leave the real one "
                f"orphaned with its conversations.\n\n"
                f"This happens when the bundle has no record of the space - a new deployment folder "
                f"(workspace.root_path), a new service principal, or a renamed bundle. Point the bundle at "
                f"the space that already exists instead of creating another:\n\n"
                f"    databricks bundle deployment bind genie_space {twin[0]} -t <target> --auto-approve\n\n"
                f"If you really do want a separate second space, give it a different space_title in "
                f"config/project.yml.")
        return "ok", True, "first deployment to this environment: the space will be created"
    etag = (entry.get("changes") or {}).get("etag") or {}
    edited = etag.get("old") is not None and etag.get("old") != etag.get("remote")
    remote = (entry.get("remote_state") or {}).get("serialized_space")
    live = json.loads(remote) if remote else None
    same = live is not None and S.normalise(live) == S.normalise(local)
    if not edited or same:
        what = "no UI edits since the last deployment" if not edited else "the UI edits are already in git"
        return "ok", True, what
    since = f"(version {etag.get('old')} deployed, live version {etag.get('remote')})"
    if policy == "keep":
        detail = "Edits in the live space that are not in git:\n" + D.markdown(D.changes(local, live))
        return "keep", False, (f"the space has newer UI edits than git {since}; not deploying, so they are kept. "
                               "The next dev-sync pull request will bring them into git.\n" + detail)
    # The plan only has hashes of the last deployed version, so the UI edit can't be isolated from this
    # release's own changes: show everything the deployment would change in the live space.
    detail = ("Deploying would make these changes to the live space (the UI edit is undone, and this release's "
              "own changes are applied):\n" + D.markdown(D.changes(live, local)))
    if policy == "overwrite":
        return "overwrite", True, f"the space was edited in the UI since the last deployment {since}; overwriting.\n" + detail
    return "refuse", False, (f"the space was edited in the UI since the last deployment {since}, which nobody "
                             "should do in this environment. Re-make the change in dev (it then comes through a "
                             "pull request), or rerun with overwrite to discard it.\n" + detail)


def title_of(entry: dict) -> str:
    return ((entry.get("new_state") or {}).get("value") or {}).get("title", "")


def existing_space_titled(title: str):
    """(space_id, title) of a space already in the workspace with this title, else None.

    A `create` plan means the bundle has no record of the space - which is also what a moved deployment
    folder or a different service principal looks like. Deploying then duplicates a live space, so the
    workspace, not the bundle's state, has to answer whether the space is really new.
    """
    if not title:
        return None
    try:
        from databricks.sdk import WorkspaceClient
        for space in WorkspaceClient().genie.list_spaces().spaces or []:
            if (space.title or "").strip() == title.strip():
                return space.space_id, space.title
    except Exception as exc:                        # no SDK, or no permission to list: don't block the deploy
        print(f"note: could not check for an existing space with this title ({type(exc).__name__}); "
              f"skipping the duplicate check")
    return None


def live_matches(plan: dict, local: dict) -> bool:
    remote = ((plan.get("plan") or {}).get(KEY, {}).get("remote_state") or {}).get("serialized_space")
    return bool(remote) and S.normalise(json.loads(remote)) == S.normalise(local)


def _output(text: str) -> None:
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--on-ui-edits", choices=["keep", "overwrite", "refuse"])
    mode.add_argument("--live-matches", action="store_true")
    ap.add_argument("--space-file", default=str(S.SPACE_FILE))
    args = ap.parse_args(argv)
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if args.live_matches:
        matches = live_matches(plan, S.load(args.space_file))
        print("The live space holds exactly this version." if matches else
              "The live space differs from this version (it has newer edits, or this is not its content): skipped.")
        _output(f"matches={'true' if matches else 'false'}")
        return 0
    verdict, deploy, why = decide(plan, S.load(args.space_file), args.on_ui_edits)
    icon = {"ok": "✅", "keep": "⏸️", "overwrite": "⚠️", "refuse": "⛔", "destroy": "⛔"}[verdict]
    print(f"{icon} {why}")
    _output(f"deploy={'true' if deploy else 'false'}")
    if os.environ.get("GITHUB_STEP_SUMMARY") and verdict != "ok":
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(f"### {icon} Live space check\n\n{why}\n")
    return {"destroy": 3, "refuse": 2}.get(verdict, 0)


if __name__ == "__main__":
    sys.exit(main())
