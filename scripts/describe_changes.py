"""What changed between two versions of the space, in words a reviewer (or the editor) understands.

    python scripts/describe_changes.py OLD.json NEW.json        # prints Markdown
OLD may be missing or empty (first version).
"""
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import space_lib as S                                                      # noqa: E402

ICONS = {"added": "➕", "removed": "➖", "changed": "✏️"}


def changes(old: dict, new: dict) -> list[dict]:
    old, new = S.normalise(old or {}), S.normalise(new or {})
    out = []
    sections = [(p, k, "id") for p, k in S.SECTIONS.items()] + [(p, k, "identifier") for p, k in S.DATA_SOURCES.items()]
    for path, kind, key in sections:
        before = {i.get(key): i for i in S.get(old, path)}
        after = {i.get(key): i for i in S.get(new, path)}
        for k in sorted(after.keys() - before.keys(), key=str):
            out.append({"what": "added", "kind": kind, "label": S.label(after[k]), "diff": []})
        for k in sorted(before.keys() - after.keys(), key=str):
            out.append({"what": "removed", "kind": kind, "label": S.label(before[k]), "diff": []})
        for k in sorted(before.keys() & after.keys(), key=str):
            if before[k] != after[k]:
                a = json.dumps(before[k], indent=2, sort_keys=True, ensure_ascii=False).splitlines()
                b = json.dumps(after[k], indent=2, sort_keys=True, ensure_ascii=False).splitlines()
                diff = [l for l in difflib.unified_diff(a, b, lineterm="", n=1) if not l.startswith(("---", "+++"))]
                out.append({"what": "changed", "kind": kind, "label": S.label(after[k]), "diff": diff})
    known = {p[0] for p in list(S.SECTIONS) + list(S.DATA_SOURCES)}
    for key in sorted((old.keys() | new.keys()) - known) if old else []:
        if old.get(key) != new.get(key):
            out.append({"what": "changed", "kind": "setting", "label": key,
                        "diff": [f"- {json.dumps(old.get(key))}", f"+ {json.dumps(new.get(key))}"]})
    return out


def markdown(found: list[dict]) -> str:
    if not found:
        return "_No changes._\n"
    lines = []
    for c in found:
        lines.append(f"- {ICONS[c['what']]} **{c['what']} {c['kind']}**: {c['label']}")
    details = [c for c in found if c["diff"]]
    if details:
        lines.append("\n<details><summary>Exact changes</summary>\n")
        for c in details:
            lines += [f"**{c['kind']}: {c['label']}**", "```diff", *c["diff"], "```"]
        lines.append("</details>")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__)
        return 2
    old_path, new_path = (Path(a) for a in argv)
    old = S.load(old_path) if old_path.exists() and old_path.stat().st_size else {}
    print(markdown(changes(old, S.load(new_path))), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
