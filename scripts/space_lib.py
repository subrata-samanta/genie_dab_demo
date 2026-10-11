"""Shared helpers for the Genie space JSON (Databricks' serialized-space format, as `bundle generate` writes it)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SPACE_FILE = ROOT / "src" / "genie_space.geniespace.json"
CONFIG_DIR = ROOT / "config"


def config() -> dict:
    """This space's configuration: config/*.yml merged, the files the bundle also includes."""
    merged: dict = {}
    for path in sorted(CONFIG_DIR.glob("*.yml")):
        for key, value in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key].update(value)
            else:
                merged[key] = value
    if not merged:
        raise SystemExit(f"no configuration found in {CONFIG_DIR.relative_to(ROOT)}/ (expected project.yml)")
    return merged


def setting(*path: str):
    """One value from the configuration, e.g. setting('variables', 'dev_catalog', 'default')."""
    node = config()
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise SystemExit(f"config/project.yml: {'.'.join(path)} is not set")
        node = node[key]
    return node

# id-bearing lists, with the words a reader understands
SECTIONS = {
    ("config", "sample_questions"): "sample question",
    ("instructions", "text_instructions"): "instruction",
    ("instructions", "example_question_sqls"): "trusted example SQL",
    ("instructions", "sql_functions"): "trusted SQL function",
    ("instructions", "join_specs"): "join",
    ("instructions", "sql_snippets", "filters"): "SQL filter",
    ("instructions", "sql_snippets", "expressions"): "SQL expression",
    ("instructions", "sql_snippets", "measures"): "SQL measure",
    ("benchmarks", "questions"): "benchmark question",
}
DATA_SOURCES = {("data_sources", "tables"): "table", ("data_sources", "metric_views"): "metric view"}
HEX32 = re.compile(r"^[0-9a-f]{32}$")
_SORT_KEYS = ("id", "identifier", "column_name", "name")


def load(path: Path | str = SPACE_FILE) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dumps(space: dict) -> str:
    """The exact text `bundle generate genie-space` writes."""
    return json.dumps(space, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def normalise(value):
    """Lists of objects sorted by id / identifier / column_name / name, so two exports compare equal."""
    if isinstance(value, dict):
        return {k: normalise(v) for k, v in value.items()}
    if isinstance(value, list):
        items = [normalise(v) for v in value]
        if items and all(isinstance(v, dict) for v in items):
            for key in _SORT_KEYS:
                if all(key in v for v in items):
                    return sorted(items, key=lambda v: str(v[key]))
        return items
    return value


def order_differences(value, path: str = "") -> list[str]:
    """Paths of lists whose order differs from normalise() (information only: Databricks' export order is fine)."""
    out = []
    if isinstance(value, dict):
        for k, v in value.items():
            out += order_differences(v, f"{path}.{k}" if path else k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out += order_differences(v, f"{path}[{i}]")
        if value and all(isinstance(v, dict) for v in value):
            key = next((k for k in _SORT_KEYS if all(k in v for v in value)), None)
            if key and [str(v[key]) for v in value] != sorted(str(v[key]) for v in value):
                out.append(f"{path} (not in {key} order)")
    return out


def get(space: dict, path: tuple) -> list:
    node = space
    for key in path:
        node = node.get(key, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, list) else []


def text(lines) -> str:
    return "".join(lines) if isinstance(lines, list) else str(lines or "")


def label(item: dict) -> str:
    """A human-readable name for one item of a section."""
    for key in ("question", "display_name", "alias", "identifier", "title"):
        if key in item:
            return " ".join(text(item[key]).split())[:100]
    if "content" in item:
        first = next((l.strip("# \n") for l in item["content"] if l.strip("# \n")), "")
        return f"{first[:80]}…"
    return str(item.get("id", "?"))


def catalogs(space: dict) -> set[str]:
    """Catalogs of the space's data sources and functions."""
    out = set()
    for path in list(DATA_SOURCES) + [("instructions", "sql_functions")]:
        for item in get(space, path):
            if "." in item.get("identifier", ""):
                out.add(item["identifier"].split(".")[0].strip("`"))
    return out
