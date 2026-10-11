"""Can the identity this job runs as actually use the space's data? Exit 1 if not.

Genie answers every question as the identity that asks it, so the service principal's access - not
yours - decides whether the deployed space works. This checks it before the space is deployed, and
names the fix, instead of leaving it to surface later as an empty answer or a 403 at deploy time.

    python scripts/check_access.py --target qa

Checks, for the catalogs the space JSON actually references:
  * who the job runs as, and whether that is a service principal (qa and prod should not deploy as a person)
  * every data source is readable (missing SELECT / USE CATALOG shows up here, not at deploy)
  * whether a readable table returns no rows at all, which is what a row filter looks like

Auth: the standard DATABRICKS_* environment variables or CLI profile. Requires: pip install databricks-sdk
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from databricks.sdk import WorkspaceClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
import space_lib as S                                                      # noqa: E402

ROW_FILTER_HINT = (
    "readable but empty. If the table is not simply empty, a row filter is excluding every row for this "
    "identity: it passes every permission check and still answers nothing. Check "
    "<catalog>.information_schema.row_filters, read the filter's function, and add this identity to a "
    "group the function admits."
)


APPLICATION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def is_service_principal(me) -> bool:
    """A service principal authenticates as its application id, a person as an email address.

    Not `me.emails`: a service principal has one too, holding that same application id.
    """
    return bool(APPLICATION_ID.match((me.user_name or "").strip()))


def data_sources(space: dict) -> list[str]:
    out = []
    for path in S.DATA_SOURCES:
        out += [t["identifier"] for t in S.get(space, path) if t.get("identifier")]
    return sorted(set(out))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True, help="dev, qa or prod (used only for the messages)")
    ap.add_argument("--warehouse-id", help="defaults to the warehouse named in config/project.yml")
    args = ap.parse_args(argv)

    w = WorkspaceClient()
    errors, warnings = [], []

    me = w.current_user.me()
    kind = "service principal" if is_service_principal(me) else "user"
    print(f"identity: {me.display_name or me.user_name} ({me.user_name}) - {kind}")
    if args.target in ("qa", "prod") and not is_service_principal(me):
        warnings.append(f"deploying {args.target} as a person, not a service principal. Databricks recommends "
                        f"a service principal per environment, so a deployment does not depend on anyone's "
                        f"personal access.")

    warehouse_id = args.warehouse_id
    if not warehouse_id:
        name = S.setting("variables", "warehouse_name", "default")
        match = [x for x in w.warehouses.list() if x.name == name]
        if not match:
            print(f"ERROR: no SQL warehouse named {name!r} is visible to this identity "
                  f"(config/project.yml: warehouse_name). It must exist in every workspace, and the "
                  f"identity needs CAN USE on it.")
            return 1
        warehouse_id = match[0].id
        print(f"warehouse: {name} ({warehouse_id})")

    for identifier in data_sources(S.load()):
        try:
            r = w.statement_execution.execute_statement(
                statement=f"SELECT 1 FROM {identifier} LIMIT 1", warehouse_id=warehouse_id, wait_timeout="50s")
            if r.status and r.status.error:
                errors.append(f"{identifier}: {r.status.error.message.splitlines()[0]}")
                continue
            rows = r.manifest.total_row_count if r.manifest and r.manifest.total_row_count is not None else \
                len((r.result.data_array if r.result else None) or [])
            if rows:
                print(f"  [ok]    {identifier}")
            else:
                print(f"  [EMPTY] {identifier}")
                warnings.append(f"{identifier}: {ROW_FILTER_HINT}")
        except Exception as exc:                                           # noqa: BLE001
            errors.append(f"{identifier}: {type(exc).__name__}: {exc}")

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print(f"\n{len(errors)} data source(s) this identity cannot read. Genie refuses to deploy a space "
              f"whose tables the agent cannot read, so fix these first:\n"
              f"  GRANT `USE CATALOG`, `USE SCHEMA`, SELECT, EXECUTE ON CATALOG <catalog> TO `<application-id>`;")
        return 1
    print(f"\nAccess OK for {args.target}." + ("  (with warnings above)" if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
