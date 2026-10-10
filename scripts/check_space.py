"""Static checks of the space JSON (no workspace needed). Exit 1 on an error.

    python scripts/check_space.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import space_lib as S                                                      # noqa: E402

V1_FIELDS = {"get_example_values": "enable_format_assistance", "build_value_dictionary": "enable_entity_matching"}


def check(space: dict, text: str, dev_catalog: str) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    if not isinstance(space.get("version"), int):
        errors.append("missing integer 'version'")
    if text != S.dumps(space):
        errors.append("the file is not formatted the way `bundle generate` writes it (2-space indent, sorted keys); "
                      "re-export it from dev instead of editing it by hand")
    if S.normalise(space) != space:
        errors.append("a list is not sorted by id / identifier (Genie rejects unsorted lists)")
    if not S.get(space, ("data_sources", "tables")) and not S.get(space, ("data_sources", "metric_views")):
        errors.append("the space has no data sources")
    seen = {}
    for path, kind in S.SECTIONS.items():
        for item in S.get(space, path):
            i = item.get("id")
            if not i or not S.HEX32.match(str(i)):
                errors.append(f"{kind} {S.label(item)!r}: id must be 32 lowercase hex characters, got {i!r}")
            elif i in seen:
                errors.append(f"duplicate id {i} ({seen[i]} and {kind})")
            seen[i] = kind
    if space.get("version", 0) >= 2:
        for t in S.get(space, ("data_sources", "tables")):
            for c in t.get("column_configs") or []:
                for old, new in V1_FIELDS.items():
                    if old in c:
                        errors.append(f"{t.get('identifier')}.{c.get('column_name')}: '{old}' is a version 1 field; "
                                      f"version 2 uses '{new}'")
    other = S.catalogs(space) - {dev_catalog}
    if other:
        errors.append(f"data sources must use the dev catalog {dev_catalog!r} (the JSON is exported from dev); "
                      f"found {sorted(other)}")
    graded = [b for b in S.get(space, ("benchmarks", "questions"))
              if any(a.get("format") == "SQL" and a.get("content") for a in b.get("answer", []))]
    if not graded:
        warnings.append("no benchmark question has an expected SQL answer: the QA benchmark gate will fail. "
                        "Add benchmarks in the dev space (Benchmarks tab).")
    return errors, warnings


def main() -> int:
    cfg = yaml.safe_load((S.ROOT / "databricks.yml").read_text(encoding="utf-8"))
    dev_catalog = cfg["variables"]["dev_catalog"]["default"]
    if not S.SPACE_FILE.exists():
        print(f"{S.SPACE_FILE.relative_to(S.ROOT)} does not exist yet: run the bootstrap workflow first.")
        return 1
    text = S.SPACE_FILE.read_text(encoding="utf-8")
    errors, warnings = check(S.load(), text, dev_catalog)
    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    counts = {kind: len(S.get(S.load(), path)) for path, kind in {**S.DATA_SOURCES, **S.SECTIONS}.items()}
    print("space:", ", ".join(f"{n} {k}(s)" for k, n in counts.items() if n))
    print("OK" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
